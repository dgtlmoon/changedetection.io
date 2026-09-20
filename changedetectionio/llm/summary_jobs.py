"""Background generation of AI change summaries.

The diff-page / watch-list "Summary" button used to hold a request thread for the entire LLM
round-trip (seconds, or the whole provider timeout).  Instead the route now starts the work here
and answers immediately with 202.  The browser learns the summary is ready either from the
``llm_summary_ready`` Socket.IO event (when realtime is enabled) or by polling the route (when it
is not) - see static/js/llm-summary.js.

Note what is *not* stored in this module: the summary itself.  The job writes it to the watch's
on-disk cache (``Watch.save_llm_diff_summary``), which every reader already consults, so there is
no result registry to keep in sync and no memory that grows with history.  All this holds is
"something is already running for this key" (so polling can never start a second generation and
pay for the same summary twice) and "the last attempt failed" (so a failure reaches the next poll
instead of dying with the thread and leaving the browser on a permanent spinner).

A process restart therefore loses only the in-flight bookkeeping: the next poll sees neither a
cache entry nor a pending job, and restarts the work.
"""

import os
import threading
from concurrent.futures import ThreadPoolExecutor

from loguru import logger

# Bounded on purpose: this is the ceiling on concurrent LLM calls started from the UI, so a
# handful of operators clicking "Summary" at once cannot fan out into provider rate-limiting
# or a surprise token bill.  Extra clicks queue.
DEFAULT_MAX_WORKERS = 2


class SummaryJobFailed(Exception):
    """A handled failure that should be reported to the next poll with a specific HTTP status."""

    def __init__(self, message, http_status=500):
        super().__init__(message)
        self.message = message
        self.http_status = http_status


class SummaryJobRegistry:
    """In-flight tracking + a small thread pool for on-demand summary generation."""

    def __init__(self, max_workers=None):
        self._lock = threading.Lock()
        self._pending = set()
        self._errors = {}  # key -> (http_status, message)
        self._pool = None
        self._max_workers = max_workers or int(os.getenv('LLM_SUMMARY_WORKERS', DEFAULT_MAX_WORKERS))

    def _get_pool(self):
        """Created on first use - importing this module must never spawn threads.

        Threads started at import time would be alive before ``gc.freeze()`` runs in flask_app,
        and would be inherited by any subprocess the restock processor spawns.
        """
        if self._pool is None:
            self._pool = ThreadPoolExecutor(
                max_workers=self._max_workers,
                thread_name_prefix='llm-summary',
            )
        return self._pool

    def is_pending(self, key):
        with self._lock:
            return key in self._pending

    def take_error(self, key):
        """Pop the stored failure for `key`, or None.

        Popping (rather than peeking) means an error is delivered to exactly one poll: the browser
        shows it and stops, and a later deliberate click is free to retry from scratch.
        """
        with self._lock:
            return self._errors.pop(key, None)

    def submit(self, key, fn, on_settled=None):
        """Run `fn()` on the pool unless `key` is already running.

        `fn` is responsible for persisting its own result before returning; see the ordering note
        in `_run`.  `on_settled(key)` is called once the job has finished either way - used to
        signal the browser over Socket.IO so it does not have to poll.  Returns True if this call
        started the work, False if it was already in flight.
        """
        with self._lock:
            if key in self._pending:
                logger.debug(f"LLM summary job already in flight, not starting a second: {key}")
                return False
            # Marked pending *before* the pool sees it, so a poll arriving between submit() and
            # the worker actually starting still gets 'pending' rather than 'idle'.
            self._pending.add(key)
            self._errors.pop(key, None)

        try:
            self._get_pool().submit(self._run, key, fn, on_settled)
        except Exception:
            with self._lock:
                self._pending.discard(key)
            raise
        return True

    def _run(self, key, fn, on_settled=None):
        try:
            fn()
        except SummaryJobFailed as e:
            with self._lock:
                self._errors[key] = (e.http_status, e.message)
        except Exception as e:
            logger.error(f"LLM summary job failed for {key}: {e}")
            with self._lock:
                self._errors[key] = (500, str(e))
        finally:
            # Cleared last, and only after fn() has written its result to the summary cache.
            # The reverse order would open a window where a poll sees no pending job and no cached
            # summary, decides nothing is running, and pays for the same generation again.
            with self._lock:
                self._pending.discard(key)

            # Announced only after the flag is cleared and the result (or error) is readable, so
            # the single fetch a notified client makes cannot come back "still pending" and leave
            # it waiting for an event that has already been sent.
            if on_settled:
                try:
                    on_settled(key)
                except Exception as e:
                    logger.warning(f"LLM summary on_settled callback failed for {key}: {e}")


# Process-wide instance used by the UI routes.
summary_jobs = SummaryJobRegistry()
