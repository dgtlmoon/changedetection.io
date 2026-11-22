#!/usr/bin/env python3

"""The watch_last_viewed_updated plugin hook: every path that marks a watch as viewed saves last_viewed and then
reports it, and nothing a plugin does (returning a value, raising) can stop the save."""

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


def test_watch_last_viewed_updated_hook(client, live_server, measure_memory_usage, datastore_path):
    from changedetectionio.pluggy_interface import plugin_manager, hookimpl

    seen = []

    class ViewLog:
        @hookimpl
        def watch_last_viewed_updated(self, watch, timestamp, source):
            # Called after the save
            assert watch['last_viewed'] == timestamp
            seen.append((watch.get('uuid'), source, timestamp))

    uuid, watch = _watch_with_a_change(client, datastore_path)
    newest, second_newest = sorted((int(k) for k in watch.history.keys()))[::-1][:2]

    plugin_manager.register(ViewLog(), 'test_view_log')
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
        plugin_manager.unregister(name='test_view_log')

    assert [s[1] for s in seen] == ['history', 'mark_unviewed', 'mark_viewed', 'mark_unviewed', 'mark_all_viewed']
    assert all(s[0] == uuid for s in seen)
    assert seen[0][2] >= newest
    assert seen[1][2] == second_newest, "mark_unviewed passes the wound-back timestamp"

    delete_all_watches(client)


def test_plugin_cannot_stop_last_viewed_being_saved(client, live_server, measure_memory_usage, datastore_path):
    from changedetectionio.pluggy_interface import plugin_manager, hookimpl

    class ReturnsSomething:
        @hookimpl
        def watch_last_viewed_updated(self, watch):
            return True

    class Raises:
        @hookimpl
        def watch_last_viewed_updated(self, watch):
            raise RuntimeError("broken plugin")

    uuid, watch = _watch_with_a_change(client, datastore_path)

    plugin_manager.register(ReturnsSomething(), 'test_returns_something')
    plugin_manager.register(Raises(), 'test_raises')
    try:
        assert client.get(url_for('ui.ui_diff.diff_history_page', uuid=uuid)).status_code == 200
        assert not watch.has_unviewed
        _bulk(client, 'mark-unviewed', uuid)
        assert watch.has_unviewed
        _bulk(client, 'mark-viewed', uuid)
        assert not watch.has_unviewed
    finally:
        plugin_manager.unregister(name='test_returns_something')
        plugin_manager.unregister(name='test_raises')

    delete_all_watches(client)
