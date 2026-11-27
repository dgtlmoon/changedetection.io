"""The plugin's own state, kept in {datastore}/cdio_example_fallback_fetcher-state.json next to its settings:
the times of the successful scraping API calls in the last 24 hours, for the daily limit.

    {"successful_calls": [1793700000.1, 1793703600.4, ...]}

Read once, then kept in memory, so the watch list and settings page can show the count without touching the
disk. Written after each successful call (atomically, a crash can't leave half a file). Checks run in several
threads at once, hence the lock.
"""
import json
import os
import threading
import time

WINDOW_SECONDS = 24 * 3600

_lock = threading.Lock()
_calls = None  # list of epoch seconds, loaded on first use


def _path():
    from . import PLUGIN_ID, datastore
    return os.path.join(datastore.datastore_path, f"{PLUGIN_ID}-state.json") if datastore else None


def _load():
    global _calls
    if _calls is None:
        _calls = []
        path = _path()
        if path and os.path.isfile(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    _calls = [float(t) for t in json.load(f).get('successful_calls', [])]
            except (OSError, ValueError, TypeError, AttributeError):
                _calls = []
    cutoff = time.time() - WINDOW_SECONDS
    _calls = [t for t in _calls if t > cutoff]
    return _calls


def calls_in_window():
    """Times of the successful calls in the last 24 hours, oldest first."""
    with _lock:
        return list(_load())


def record_successful_call():
    with _lock:
        calls = _load()
        calls.append(time.time())
        path = _path()
        if not path:
            return
        tmp = f"{path}.tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'successful_calls': calls}, f)
        os.replace(tmp, path)


def reset():
    """Forget the in-memory copy, the next use reads the file again (tests, or a changed datastore)."""
    global _calls
    with _lock:
        _calls = None
