"""Template context needed to render a single watch list row.

watch-overview-single-row.html is rendered from two places: inline by the watch list page
(via {% include %} inside the row loop) and standalone when a row is pushed over Socket.IO.
Both MUST build their context here — if they build it separately the pushed row silently
drifts from the server-rendered one, which is the bug class this exists to prevent.

Only names the row cannot get for itself belong here. Anything registered app-wide
(`is_checking_now` template global, `fetcher_status_icons` filter, `url_for`, `_()`) is
already available in any render and is deliberately NOT listed.
"""

from changedetectionio import processors


class _LazyProcessorBadgeTexts:
    """Resolve restock badge text only for rows the template renders."""

    def __init__(self, datastore, watches, processor_badge_texts):
        self._datastore = datastore
        self._processor_badge_texts = processor_badge_texts
        self._restock_watches = {
            watch.get('uuid'): watch
            for watch in watches
            if watch.get('processor') == 'restock_diff'
        }
        self._cache = {}

    def get(self, watch_uuid, default=None):
        watch = self._restock_watches.get(watch_uuid)
        if watch is None:
            return default

        if watch_uuid not in self._cache:
            from changedetectionio.processors.restock_diff.processor import get_restock_settings

            badge_text = self._processor_badge_texts.get('restock_diff', default)
            if get_restock_settings(self._datastore, watch).get('in_stock_processing') == 'off':
                # ``Price`` is already part of the extracted catalog (the row's price
                # column uses it); call the package's locale-aware gettext here without
                # creating a second extractor location for the same msgid.
                from flask_babel import gettext as _translate
                badge_text = _translate('Price')
            self._cache[watch_uuid] = badge_text

        return self._cache[watch_uuid]

    def __getitem__(self, watch_uuid):
        watch = self._restock_watches.get(watch_uuid)
        if watch is None:
            raise KeyError(watch_uuid)
        return self.get(watch_uuid)


def processor_badge_texts_for_watches(datastore, watches, processor_badge_texts):
    """Return lazily resolved badge text for watches in a rendered list.

    Most processor badges are fixed by processor type. Restock watches are the
    exception: when availability detection is disabled, the watch only tracks
    price changes and should be labelled accordingly. The effective settings
    include tag overrides, so use the same resolver as the restock processor.
    Resolution is lazy because pagination renders only a subset of ``watches``;
    reading config files for rows outside the current page would waste I/O.
    """
    return _LazyProcessorBadgeTexts(datastore, watches, processor_badge_texts)


def watch_row_context(datastore, active_tag_uuid=None, queued_uuids=None,
                      processor_badge_texts_by_watch=None):
    """Context for one (or many) watch list rows.

    active_tag_uuid matters: the row's Edit/Recheck links carry the tag so the operator lands
    back on the filtered view they came from. A pushed row must therefore be rendered with the
    tag of the page that will receive it, not a global one.

    queued_uuids is accepted so a caller rendering many rows can fetch the queue once instead
    of per row; omit it and the live queue is read for you.

    processor_badge_texts_by_watch allows a list page to provide the effective
    per-watch badge label without making the row template read configuration files.
    """
    if queued_uuids is None:
        # Local import: flask_app imports blueprints, so a module-level import would cycle.
        from changedetectionio.flask_app import update_q
        queued_uuids = update_q.get_queued_uuids()

    return {
        'active_tag_uuid': active_tag_uuid,
        # Kept 0 (rather than any_watches_have_processor_by_name) while the price column is
        # disabled — it also decides cols_required on the page, so page and row must agree or
        # a pushed row ends up with a different <td> count than the table header.
        'any_has_restock_price_processor': 0,
        'datastore': datastore,
        'has_proxies': datastore.proxy_list,
        'processor_descriptions': processors.get_processor_descriptions(),
        'processor_badge_texts_by_watch': processor_badge_texts_by_watch or {},
        'queued_uuids': queued_uuids,
        'system_default_fetcher': datastore.data['settings']['application'].get('fetch_backend'),
        'ui_settings': datastore.data['settings']['application']['ui'],
    }
