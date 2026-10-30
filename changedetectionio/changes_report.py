"""
Every change across a group of watches between two dates, as compact unified diffs.

Used by GET /api/v1/changes (api/Changes.py) and meant to be shared with the MCP `get_changes` tool:
the question "what changed across these 1,800 watches this month?" takes one call instead of one
per watch.

Works for any processor, since every processor stores its history as text (a restock/price watch's
snapshot holds its price and stock text). The output is plain `difflib.unified_diff`, which people
and language models both read well, under a short header per watch with its title, URL and uuid.

Modes:
    net_change  latest snapshot at or before `from` vs the latest at or before `to` (default)
    each        one diff per snapshot inside the range, against the one before it

A watch whose text changed and then changed back has an empty net diff. It's still listed, with
"N changes, no net difference" and no diff, so the reader knows something happened (mode=each, or
the per-watch difference endpoint, shows what).
"""
import difflib
from datetime import datetime, timezone

MODES = ('net_change', 'each')


def parse_timestamp(value):
    """Unix seconds, or an ISO date/datetime (UTC unless it says otherwise). None if it can't be read."""
    if value is None or str(value).strip() == '':
        return None
    value = str(value).strip()
    if value.lstrip('-').isdigit():
        return int(value)
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def _iso(timestamp):
    return datetime.fromtimestamp(int(timestamp), tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _unified(before, after, before_ts, after_ts, context):
    lines = list(difflib.unified_diff(
        (before or '').splitlines(), (after or '').splitlines(),
        fromfile=_iso(before_ts), tofile=_iso(after_ts), n=context, lineterm=''))
    return lines


def select_watches(datastore, tag=None, uuids=None):
    """The watches in a tag/group (by uuid or name), or the given uuids, or all of them.

    Raises LookupError with a readable message when the tag or a uuid doesn't exist.
    """
    watching = datastore.data['watching']
    tag = (tag or '').strip()
    uuids = [u.strip() for u in (uuids or []) if u and u.strip()]
    if tag:
        tags = datastore.data['settings']['application']['tags']
        tag_uuid = tag if tag in tags else next(
            (uuid for uuid, t in tags.items() if (t.get('title') or '').strip().lower() == tag.lower()), None)
        if not tag_uuid:
            raise LookupError(f"No tag/group with the UUID or name '{tag}'")
        return [w for w in watching.values() if tag_uuid in (w.get('tags') or [])]
    if uuids:
        missing = [u for u in uuids if u not in watching]
        if missing:
            raise LookupError(f"No watch exists with the UUID of {', '.join(missing)}")
        return [watching[u] for u in uuids]
    return list(watching.values())


def watch_changes(watch, from_ts, to_ts, mode='net_change', context=1, max_lines=200):
    """The changes of one watch between from_ts (exclusive) and to_ts (inclusive), or None if it had none.

    Returns {'uuid', 'title', 'url', 'changes', 'new_in_period', 'no_net_difference', 'error',
             'from_timestamp', 'to_timestamp', 'diff', 'truncated'}
    """
    history = watch.history
    if not history:
        return None
    keys = sorted(int(k) for k in history.keys())

    in_range = [k for k in keys if from_ts < k <= to_ts]
    if not in_range:
        return None

    before = [k for k in keys if k <= from_ts]
    new_in_period = not before
    if new_in_period:
        # First seen inside the range: its first snapshot is the starting point, not a change
        baseline = in_range.pop(0)
    else:
        baseline = before[-1]
    if not in_range:
        # Only the first snapshot of a new watch falls in the range, nothing to compare it with yet
        return None

    def text(ts):
        return watch.get_history_snapshot(timestamp=str(ts)) or ''

    lines = []
    if mode == 'each':
        previous_ts, previous_text = baseline, text(baseline)
        for ts in in_range:
            current = text(ts)
            lines.extend(_unified(previous_text, current, previous_ts, ts, context))
            previous_ts, previous_text = ts, current
    else:
        lines = _unified(text(baseline), text(in_range[-1]), baseline, in_range[-1], context)

    truncated = False
    if max_lines and len(lines) > max_lines:
        hidden = len(lines) - max_lines
        lines = lines[:max_lines] + [f"... {hidden} more lines, see /api/v1/watch/{watch.get('uuid')}/difference/{baseline}/{in_range[-1]}"]
        truncated = True

    return {
        'uuid': watch.get('uuid'),
        'title': watch.label,
        'url': watch.get('url'),
        'changes': len(in_range),
        'new_in_period': new_in_period,
        'no_net_difference': not lines,
        'error': watch.get('last_error') or None,
        'from_timestamp': baseline,
        'to_timestamp': in_range[-1],
        'diff': '\n'.join(lines),
        'truncated': truncated,
    }


def group_changes(watches, from_ts, to_ts, mode='net_change', context=1, max_lines=200, limit=50, offset=0,
                  time_budget=None):
    """watch_changes() for each watch that changed, most recently changed first, paged with limit/offset.

    This runs inside a web request in the single app process (threaded, or gevent), so it yields between
    watches (time.sleep(0) releases the GIL, or lets other greenlets run) and stops after `time_budget`
    seconds, returning what it has with 'incomplete': True rather than holding the request open.

    Returns {'from', 'to', 'mode', 'total', 'offset', 'limit', 'monitors_checked', 'changes_total', 'watches': [...]}
    (total = monitors that changed, changes_total = changes across all of them, monitors_checked = monitors looked at)
    """
    import time

    changed = []
    watches = list(watches)
    deadline = time.monotonic() + time_budget if time_budget else None
    incomplete = False
    for watch in watches:
        if deadline and time.monotonic() > deadline:
            incomplete = True
            break
        time.sleep(0)
        # last_changed only uses the cached newest history key (0 when it isn't known yet), so this rules out
        # watches that haven't changed since `from` without reading anything. The rest read their history once.
        newest = watch.last_changed
        if newest and newest <= from_ts:
            continue
        result = watch_changes(watch, from_ts, to_ts, mode=mode, context=context, max_lines=max_lines)
        if result:
            changed.append(result)

    changed.sort(key=lambda r: r['to_timestamp'], reverse=True)
    return {
        'from': from_ts,
        'to': to_ts,
        'mode': mode,
        'total': len(changed),
        'offset': offset,
        'limit': limit,
        'monitors_checked': len(watches),
        'changes_total': sum(r['changes'] for r in changed),
        'incomplete': incomplete,
        'watches': changed[offset:offset + limit] if limit else changed[offset:],
    }


def render_unified(report):
    """The report as plain text: one summary line, then a header and unified diff per watch."""
    shown = report['watches']
    first = report['offset'] + 1 if shown else 0
    out = [f"# {report['total']} of {report['monitors_checked']} monitors changed ({report['changes_total']} changes), "
           f"{_iso(report['from'])} -> {_iso(report['to'])}, mode={report['mode']}, "
           f"showing {first}-{report['offset'] + len(shown)}"]

    if report.get('incomplete'):
        out.append("# Incomplete: stopped at the time limit before every monitor was looked at. "
                   "Narrow it down with a tag, a list of uuids or a shorter period.")

    for w in shown:
        notes = [f"{w['changes']} change{'s' if w['changes'] != 1 else ''}"
                 + (', no net difference' if w['no_net_difference'] else '')]
        if w['new_in_period']:
            notes.append('new in period')
        if w['error']:
            notes.append(f"erroring: {w['error']}")
        out.append('')
        out.append(f"### {w['title']} - {w['url']}")
        out.append(f"uuid: {w['uuid']} | {_iso(w['from_timestamp'])} -> {_iso(w['to_timestamp'])} | " + ' | '.join(notes))
        if w['diff']:
            out.append(w['diff'])

    return '\n'.join(out) + '\n'
