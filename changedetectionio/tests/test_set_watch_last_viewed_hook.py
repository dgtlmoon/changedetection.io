#!/usr/bin/env python3

"""The set_watch_last_viewed plugin hook: every path that marks a watch as viewed goes through it, a plugin
returning None only observes, and one returning anything else replaces the save."""

from flask import url_for

from .util import set_original_response, set_modified_response, wait_for_all_checks, delete_all_watches, \
    extract_UUID_from_client


def _watch_with_a_change(client, datastore_path):
    set_original_response(datastore_path=datastore_path)
    client.post(url_for("ui.ui_views.form_quick_watch_add"),
                data={"url": url_for('test_endpoint', _external=True), "tags": ''}, follow_redirects=True)
    wait_for_all_checks(client)
    set_modified_response(datastore_path=datastore_path)
    client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    uuid = extract_UUID_from_client(client)
    watch = client.application.config.get('DATASTORE').data['watching'][uuid]
    assert watch.history_n == 2 and watch.has_unviewed
    return uuid, watch


def _bulk(client, op, uuid):
    return client.post(url_for("ui.form_watch_list_checkbox_operations"), data={"op": op, "uuids": uuid},
                       follow_redirects=True)


def test_set_watch_last_viewed_hook(client, live_server, measure_memory_usage, datastore_path):
    from changedetectionio.pluggy_interface import plugin_manager, hookimpl

    seen = []

    class Observer:
        @hookimpl
        def set_watch_last_viewed(self, watch, timestamp, source):
            seen.append((watch.get('uuid'), source, timestamp))
            return None

    class Replacer:
        @hookimpl
        def set_watch_last_viewed(self, source):
            seen.append(('replaced', source))
            return True

    uuid, watch = _watch_with_a_change(client, datastore_path)
    newest, second_newest = sorted((int(k) for k in watch.history.keys()))[::-1][:2]

    # Returning None only observes, core still saves
    plugin_manager.register(Observer(), 'test_last_viewed_observer')
    try:
        assert client.get(url_for('ui.ui_diff.diff_history_page', uuid=uuid)).status_code == 200
        assert not watch.has_unviewed
        _bulk(client, 'mark-unviewed', uuid)
        assert watch.has_unviewed and watch['last_viewed'] == second_newest
        _bulk(client, 'mark-viewed', uuid)
        assert not watch.has_unviewed
        _bulk(client, 'mark-unviewed', uuid)
        client.post(url_for('ui.mark_all_viewed'), follow_redirects=True)
        assert not watch.has_unviewed
    finally:
        plugin_manager.unregister(name='test_last_viewed_observer')

    assert [s[1] for s in seen] == ['history', 'mark_unviewed', 'mark_viewed', 'mark_unviewed', 'mark_all_viewed']
    assert all(s[0] == uuid for s in seen)
    assert seen[1][2] == second_newest, "mark_unviewed passes the wound-back timestamp"
    assert seen[0][2] >= newest

    # Returning anything else replaces the save
    _bulk(client, 'mark-unviewed', uuid)
    seen.clear()
    plugin_manager.register(Replacer(), 'test_last_viewed_replacer')
    try:
        assert client.get(url_for('ui.ui_diff.diff_history_page', uuid=uuid)).status_code == 200
        _bulk(client, 'mark-viewed', uuid)
        client.post(url_for('ui.mark_all_viewed'), follow_redirects=True)
        assert watch['last_viewed'] == second_newest, "The plugin took over, core didn't save"
        assert watch.has_unviewed
    finally:
        plugin_manager.unregister(name='test_last_viewed_replacer')

    assert seen == [('replaced', 'history'), ('replaced', 'mark_viewed'), ('replaced', 'mark_all_viewed')]

    _bulk(client, 'mark-viewed', uuid)
    assert not watch.has_unviewed, "Back to core saving it"

    delete_all_watches(client)
