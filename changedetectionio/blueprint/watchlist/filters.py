"""Watch-list filtering — the single source of truth for "which watches match the
current view".

Shared by the watch list (the rendered table + the /uuids endpoint) and by the
bulk actions in the ui blueprint (mark-all-viewed, recheck-all) so a filtered view
and any action taken on it always operate on the SAME set. Keeping these as plain
functions (rather than duplicated per blueprint) is what stops the action buttons
from drifting away from the list's filter.
"""


def resolve_active_tag_uuid(datastore, active_tag_req):
    if not active_tag_req:
        return None
    for uuid, tag in datastore.data['settings']['application'].get('tags', {}).items():
        if active_tag_req == tag.get('title', '').lower().strip() or active_tag_req == uuid:
            return uuid
    return None


def list_filters_from_args(datastore, args):
    active_tag_req = (args.get('tag') or '').lower().strip()
    return {
        'with_errors': args.get('with_errors') == "1",
        'unread_only': args.get('unread') == "1",
        'deals': args.get('deals') == "1",
        'processor': (args.get('processor') or '').strip(),
        'tag_uuid': resolve_active_tag_uuid(datastore, active_tag_req),
        'search_q': args.get('q').strip().lower() if args.get('q') else False,
    }


def watch_is_deal(watch):
    """A restock/price watch whose latest check reported a price DROP."""
    if not watch.has_restock_info:
        return False
    restock = watch['restock']
    # Defensive: restock should be a Restock, but some sources (e.g. the LLM restock fallback
    # plugin) can leave a plain dict. Normalise so .get_price_change_percent() always exists
    # and a rendering of the watchlist can't 500 over it. Lazy import avoids an import cycle.
    if not hasattr(restock, 'get_price_change_percent'):
        from changedetectionio.processors.restock_diff import Restock
        restock = Restock(restock)
    pct = restock.get_price_change_percent()
    return pct is not None and pct < 0


def watch_matches_tag(watch, f):
    return not f['tag_uuid'] or f['tag_uuid'] in watch['tags']


def watch_in_context(watch, f):
    """Tag + processor — the working set the operator is looking at."""
    if not watch_matches_tag(watch, f):
        return False
    if f['processor'] and watch.get('processor') != f['processor']:
        return False
    return True


def watch_passes_status(watch, f):
    """The mutually-presented status toggle (All / Unread / Deals / With errors)."""
    if f['with_errors'] and not watch.get('last_error'):
        return False
    if f['unread_only'] and (watch.viewed or watch.last_changed == 0):
        return False
    if f['deals'] and not watch_is_deal(watch):
        return False
    return True


def watch_passes_search(watch, f):
    search_q = f['search_q']
    if not search_q:
        return True
    if (watch.get('title') and search_q in watch.get('title').lower()) or search_q in watch.get('url', '').lower():
        return True
    if watch.get('last_error') and search_q in watch.get('last_error').lower():
        return True
    return False


def watch_matches_filters(watch, f):
    """The full filter the watch list applies: context + status + search."""
    return watch_in_context(watch, f) and watch_passes_status(watch, f) and watch_passes_search(watch, f)


def matching_watch_uuids(datastore, args):
    """UUIDs of every watch matching the watch-list filters in `args` (no pagination)."""
    f = list_filters_from_args(datastore, args)
    return [uuid for uuid, watch in datastore.data['watching'].items() if watch_matches_filters(watch, f)]


# The query-string keys that define a watch-list view.
FILTER_KEYS = ('tag', 'processor', 'unread', 'with_errors', 'deals', 'q')


def filter_query_args(args):
    """The active filter params (drop blanks) — used to redirect back to the same
    filtered view after a bulk action so the operator doesn't lose their filters."""
    return {k: args.get(k) for k in FILTER_KEYS if args.get(k)}
