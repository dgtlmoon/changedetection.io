from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone

from .models import CheckResult, MonitorConfig
from .monitor import GitHubMonitor


class MonitorScheduler:
    """A single-worker scheduler that serializes state writes and API checks."""

    def __init__(self, monitor: GitHubMonitor, callback: Callable[[CheckResult], None]):
        self.monitor = monitor
        self.callback = callback
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._jobs: dict[str, MonitorConfig] = {}
        self._due: dict[str, float] = {}
        self._token = ""

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())

    def start(self, jobs: list[MonitorConfig], token: str = "") -> None:
        with self._lock:
            self._jobs = {job.job_id: job for job in jobs}
            self._token = token
            now = time.monotonic()
            self._due = {job_id: now for job_id in self._jobs}
            if self.running:
                self._wake.set()
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="github-monitor", daemon=True)
            self._thread.start()

    def update(self, jobs: list[MonitorConfig], token: str = "") -> None:
        with self._lock:
            previous = set(self._jobs)
            self._jobs = {job.job_id: job for job in jobs}
            self._token = token
            now = time.monotonic()
            self._due = {
                job_id: self._due.get(job_id, now if job_id not in previous else now + job.interval_minutes * 60)
                for job_id, job in self._jobs.items()
            }
        self._wake.set()

    def check_now(self, job_id: str | None = None) -> None:
        with self._lock:
            now = time.monotonic()
            for current in self._jobs:
                if job_id is None or current == job_id:
                    self._due[current] = now
        self._wake.set()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=timeout)

    def _run(self) -> None:
        while not self._stop.is_set():
            job: MonitorConfig | None = None
            token = ""
            wait_for = 30.0
            with self._lock:
                if self._jobs:
                    now = time.monotonic()
                    job_id = min(self._jobs, key=lambda value: self._due.get(value, now))
                    due = self._due.get(job_id, now)
                    wait_for = max(0.0, min(30.0, due - now))
                    if due <= now:
                        job = self._jobs[job_id]
                        token = self._token
                        self._due[job_id] = float("inf")
            if job is None:
                self._wake.wait(wait_for)
                self._wake.clear()
                continue
            try:
                result = self.monitor.check(job, token)
            except Exception as exc:  # Keep the scheduler alive after an unexpected local I/O failure.
                checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                result = CheckResult(job.job_id, job.display_name, checked_at, warnings=[f"检查程序异常：{exc}"])
            try:
                self.callback(result)
            finally:
                with self._lock:
                    if job.job_id in self._jobs:
                        current = self._jobs[job.job_id]
                        self._due[job.job_id] = time.monotonic() + current.interval_minutes * 60
