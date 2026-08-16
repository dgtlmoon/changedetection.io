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


def watch_row_context(datastore, active_tag_uuid=None, queued_uuids=None):
    """Context for one (or many) watch list rows.

    active_tag_uuid matters: the row's Edit/Recheck links carry the tag so the operator lands
    back on the filtered view they came from. A pushed row must therefore be rendered with the
    tag of the page that will receive it, not a global one.

    queued_uuids is accepted so a caller rendering many rows can fetch the queue once instead
    of per row; omit it and the live queue is read for you.
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
        'queued_uuids': queued_uuids,
        'system_default_fetcher': datastore.data['settings']['application'].get('fetch_backend'),
        'ui_settings': datastore.data['settings']['application']['ui'],
    }
