#!/usr/bin/env python3
"""The check_stats example plugin (example_plugins/lifecycle/check_stats): update_handler_alter and
update_finalize time a check, watch_list_extra_text and ui_edit_stats_extras show it, and
get_html_head_extras + plugin_static_path serve its CSS."""
import os

import pytest
from flask import url_for

from .util import wait_for_all_checks, delete_all_watches, import_example_plugin


@pytest.fixture
def check_stats_plugin():
    from changedetectionio.pluggy_interface import plugin_manager

    plugin = import_example_plugin('lifecycle/check_stats', 'cdio_example_check_stats')
    plugin.STATS.clear()
    plugin_manager.register(plugin, 'cdio_example_check_stats')
    yield plugin
    plugin_manager.unregister(plugin)


def test_example_check_stats_plugin(client, live_server, measure_memory_usage, datastore_path, check_stats_plugin):
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write("<html><body>Hello</body></html>")

    client.post(url_for("ui.ui_views.form_quick_watch_add"),
                data={"url": url_for('test_endpoint', _external=True), "tags": ''}, follow_redirects=True)
    wait_for_all_checks(client)

    datastore = client.application.config.get('DATASTORE')
    uuid = next(iter(datastore.data['watching']))
    stats = check_stats_plugin.STATS.get(uuid)
    assert stats and stats['ok'] and stats['count'] >= 1, f"The check should have been timed, got {stats}"

    # Watch list note
    res = client.get(url_for("watchlist.index"))
    assert b'<div class="extra-watch-text">Last check took' in res.data

    # Edit page Stats tab
    res = client.get(url_for("ui.ui_edit.edit_page", uuid=uuid))
    assert b'cdio-example-check-stats' in res.data
    assert b'Checks timed since restart' in res.data

    # CSS linked in <head> and served from the plugin's static directory
    assert b'/static/plugin/cdio_example_check_stats.css' in res.data
    res = client.get('/static/plugin/cdio_example_check_stats.css')
    assert res.status_code == 200
    assert b'.cdio-example-check-stats' in res.data

    # Listed under Settings > Info as an active plugin, with its docstring's first line
    res = client.get(url_for("settings.settings_page"))
    assert b'<li><strong>cdio_example_check_stats</strong> - Example plugin - times every check' in res.data

    delete_all_watches(client)


def test_watch_list_extra_text_is_escaped(client, live_server, measure_memory_usage, datastore_path):
    """watch_list_extra_text is plain text, a plugin can't inject HTML into the watch list."""
    from changedetectionio.pluggy_interface import plugin_manager, hookimpl

    class Notes:
        @hookimpl
        def watch_list_extra_text(self, watch):
            return ['<b>bold?</b>', 'second note']

    plugin_manager.register(Notes(), 'test_watch_list_notes')
    try:
        client.post(url_for("ui.ui_views.form_quick_watch_add"),
                    data={"url": url_for('test_endpoint', _external=True), "tags": '', "paused": "y"}, follow_redirects=True)
        res = client.get(url_for("watchlist.index"))
        assert b'<div class="extra-watch-text">&lt;b&gt;bold?&lt;/b&gt;</div>' in res.data
        assert b'<div class="extra-watch-text">second note</div>' in res.data
        assert b'<b>bold?</b>' not in res.data
    finally:
        plugin_manager.unregister(name='test_watch_list_notes')
        delete_all_watches(client)
