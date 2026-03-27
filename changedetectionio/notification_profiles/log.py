"""
Per-profile notification log.

Each profile gets its own log file at:
  {datastore_path}/notification-logs/{profile_uuid}.log

Entries are stored as JSON-lines (one JSON object per line).
The file is capped at MAX_ENTRIES lines (oldest pruned first).
"""

import json
import os
from datetime import datetime, timezone

MAX_ENTRIES = 100
_LOG_DIR = 'notification-logs'


def _log_file(datastore_path: str, profile_uuid: str) -> str:
    return os.path.join(datastore_path, _LOG_DIR, f'{profile_uuid}.log')


def write_profile_log(datastore_path: str, profile_uuid: str, *,
                      watch_url: str = '',
                      watch_uuid: str = '',
                      status: str,        # 'ok' | 'error' | 'test'
                      message: str = ''):
    """Append one log entry; prune to MAX_ENTRIES."""
    log_dir = os.path.join(datastore_path, _LOG_DIR)
    os.makedirs(log_dir, exist_ok=True)

    entry = json.dumps({
        'ts':         datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
        'watch_url':  watch_url[:200],
        'watch_uuid': watch_uuid,
        'status':     status,
        'message':    message[:500],
    }, ensure_ascii=False)

    path = _log_file(datastore_path, profile_uuid)
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            lines = [l for l in fh.read().splitlines() if l.strip()]
    except FileNotFoundError:
        lines = []

    lines.append(entry)
    lines = lines[-MAX_ENTRIES:]

    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines) + '\n')


def read_profile_log(datastore_path: str, profile_uuid: str) -> list:
    """Return log entries as a list of dicts, newest first."""
    path = _log_file(datastore_path, profile_uuid)
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            lines = [l.strip() for l in fh if l.strip()]
    except FileNotFoundError:
        return []

    entries = []
    for line in reversed(lines):
        try:
            entries.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            pass
    return entries


def has_log(datastore_path: str, profile_uuid: str) -> bool:
    return os.path.exists(_log_file(datastore_path, profile_uuid))
