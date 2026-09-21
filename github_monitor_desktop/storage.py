from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


SCHEMA_VERSION = 1


class AppStorage:
    def __init__(self, root: str | Path | None = None):
        if root is None:
            base = Path(os.environ.get("APPDATA") or Path.home())
            root = base / "GitHubMonitor"
        self.root = Path(root)
        self.config_path = self.root / "config.json"
        self.state_path = self.root / "state.json"
        self.events_path = self.root / "events.jsonl"

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def load_config(self) -> dict:
        value = self._read_json(self.config_path, default={})
        if not isinstance(value, dict):
            return {"schema_version": SCHEMA_VERSION, "jobs": []}
        value.setdefault("schema_version", SCHEMA_VERSION)
        value.setdefault("jobs", [])
        return value

    def save_config(self, value: dict) -> None:
        payload = dict(value)
        payload["schema_version"] = SCHEMA_VERSION
        self._atomic_json(self.config_path, payload)

    def load_state(self) -> dict:
        value = self._read_json(self.state_path, default={})
        if not isinstance(value, dict):
            value = {}
        value.setdefault("schema_version", SCHEMA_VERSION)
        value.setdefault("jobs", {})
        return value

    def save_state(self, value: dict) -> None:
        payload = dict(value)
        payload["schema_version"] = SCHEMA_VERSION
        self._atomic_json(self.state_path, payload)

    def delete_job_state(self, job_id: str) -> None:
        state = self.load_state()
        state.get("jobs", {}).pop(job_id, None)
        self.save_state(state)

    def append_event(self, value: dict) -> None:
        self.ensure()
        with self.events_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True))
            handle.write("\n")

    @staticmethod
    def _read_json(path: Path, default):
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return default

    def _atomic_json(self, path: Path, value: dict) -> None:
        self.ensure()
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                delete=False,
                dir=str(path.parent),
                prefix=f".{path.name}.",
                suffix=".tmp",
            ) as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
                temp_path = Path(handle.name)
            os.replace(temp_path, path)
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink(missing_ok=True)
