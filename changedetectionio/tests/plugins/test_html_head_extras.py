"""Test that plugins can inject HTML into base.html <head> via get_html_head_extras hookimpl."""
import pytest
from flask import url_for

from changedetectionio.pluggy_interface import hookimpl, plugin_manager


class _HeadExtrasPlugin:
    """Minimal test plugin that injects a marker script tag into <head>."""

    @hookimpl
    def get_html_head_extras(self):
        return '<script id="test-head-extra">/* changedetection-head-extras-test */</script>'


@pytest.fixture
def head_extras_plugin():
    """Register the test plugin for the duration of one test, then remove it."""
    plugin = _HeadExtrasPlugin()
    plugin_manager.register(plugin, name="test_head_extras")
    yield plugin
    plugin_manager.unregister(name="test_head_extras")


def test_plugin_html_injected_into_head(client, live_server, measure_memory_usage, datastore_path, head_extras_plugin):
    """get_html_head_extras output must appear inside <head> in the rendered page."""
    res = client.get(url_for("watchlist.index"), follow_redirects=True)
    assert res.status_code == 200
    assert b'id="test-head-extra"' in res.data, (
        "Plugin-provided <script> tag should be present in the rendered page"
    )
    # Confirm it lands before </head> (i.e. actually inside <head>)
    head_end = res.data.find(b'</head>')
    marker = res.data.find(b'id="test-head-extra"')
    assert head_end != -1 and marker != -1 and marker < head_end, (
        "Plugin HTML must appear before </head>, not after"
    )


def test_no_extras_without_plugin(client, live_server, measure_memory_usage, datastore_path):
    """With no plugin registered the marker must not appear (sanity / isolation check)."""
    res = client.get(url_for("watchlist.index"), follow_redirects=True)
    assert b'id="test-head-extra"' not in res.data
