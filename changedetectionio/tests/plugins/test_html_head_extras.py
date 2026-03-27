"""Test that plugins can inject HTML into base.html <head> via get_html_head_extras hookimpl."""
import pytest
from flask import url_for, Response

from changedetectionio.pluggy_interface import hookimpl, plugin_manager

_MY_JS = "console.log('my_module_content loaded');"
_MY_CSS = ".my-module-example { color: red; }"


class _HeadExtrasPlugin:
    """Test plugin that injects tags pointing at its own Flask routes."""

    @hookimpl
    def get_html_head_extras(self):
        css_url = url_for('test_plugin_my_module_content_css')
        js_url  = url_for('test_plugin_my_module_content_js')
        return (
            f'<link rel="stylesheet" id="test-head-extra-css" href="{css_url}">\n'
            f'<script id="test-head-extra-js" src="{js_url}" defer></script>'
        )


@pytest.fixture(scope='module')
def plugin_routes(live_server):
    """Register plugin asset routes once per module (Flask routes can't be added twice)."""
    app = live_server.app

    @app.route('/test-plugin/my_module_content/css')
    def test_plugin_my_module_content_css():
        return Response(_MY_CSS, mimetype='text/css',
                        headers={'Cache-Control': 'max-age=3600'})

    @app.route('/test-plugin/my_module_content/js')
    def test_plugin_my_module_content_js():
        return Response(_MY_JS, mimetype='application/javascript',
                        headers={'Cache-Control': 'max-age=3600'})


@pytest.fixture
def head_extras_plugin(plugin_routes):
    """Register the hookimpl for one test then unregister it — function-scoped for clean isolation."""
    plugin = _HeadExtrasPlugin()
    plugin_manager.register(plugin, name="test_head_extras")
    yield plugin
    plugin_manager.unregister(name="test_head_extras")


def test_plugin_html_injected_into_head(client, live_server, measure_memory_usage, datastore_path, head_extras_plugin):
    """get_html_head_extras output must appear inside <head> in the rendered page."""
    res = client.get(url_for("watchlist.index"), follow_redirects=True)
    assert res.status_code == 200
    assert b'id="test-head-extra-css"' in res.data, "Plugin <link> tag missing from rendered page"
    assert b'id="test-head-extra-js"' in res.data,  "Plugin <script> tag missing from rendered page"

    head_end = res.data.find(b'</head>')
    assert head_end != -1
    for marker in (b'id="test-head-extra-css"', b'id="test-head-extra-js"'):
        pos = res.data.find(marker)
        assert pos != -1 and pos < head_end, f"{marker} must appear before </head>"


def test_plugin_js_route_returns_correct_content(client, live_server, measure_memory_usage, datastore_path, plugin_routes):
    """The plugin-registered JS route must return JS with the right Content-Type."""
    res = client.get(url_for('test_plugin_my_module_content_js'))
    assert res.status_code == 200
    assert 'javascript' in res.content_type
    assert _MY_JS.encode() in res.data


def test_plugin_css_route_returns_correct_content(client, live_server, measure_memory_usage, datastore_path, plugin_routes):
    """The plugin-registered CSS route must return CSS with the right Content-Type."""
    res = client.get(url_for('test_plugin_my_module_content_css'))
    assert res.status_code == 200
    assert 'css' in res.content_type
    assert _MY_CSS.encode() in res.data


def test_no_extras_without_plugin(client, live_server, measure_memory_usage, datastore_path):
    """With no hookimpl registered the markers must not appear (isolation check)."""
    res = client.get(url_for("watchlist.index"), follow_redirects=True)
    assert b'id="test-head-extra-css"' not in res.data
    assert b'id="test-head-extra-js"' not in res.data
