#!/usr/bin/env python3
"""The hello_world example plugin (example_plugins/ui/hello_world): register_blueprints mounts a page
that renders inside the normal app layout."""
import pytest
from flask import url_for

from .util import import_example_plugin


@pytest.fixture
def hello_world_plugin(live_server):
    from changedetectionio.pluggy_interface import plugin_manager, register_plugin_blueprints

    plugin = import_example_plugin('ui/hello_world', 'cdio_example_hello_world')
    plugin_manager.register(plugin, 'cdio_example_hello_world')

    app = live_server.app
    if 'cdio_example_hello_world' not in app.blueprints:
        # The app is shared by the whole test session and has already served requests, after which
        # Flask refuses new blueprints. At real startup the hook runs before the first request.
        got_first_request = app._got_first_request
        app._got_first_request = False
        try:
            register_plugin_blueprints(app, app.config['DATASTORE'])
        finally:
            app._got_first_request = got_first_request
    yield plugin
    plugin_manager.unregister(plugin)


def test_example_hello_world_plugin(client, live_server, measure_memory_usage, datastore_path, hello_world_plugin):
    res = client.get(url_for('cdio_example_hello_world.hello'))
    assert res.status_code == 200
    assert b'id="cdio-example-hello-world"' in res.data
    assert b'Hello world!' in res.data
    assert b'You have <strong>0</strong> monitors.' in res.data
    # Rendered inside base.html, not as a bare page
    assert b'<html' in res.data and b'</head>' in res.data
    assert url_for('watchlist.index').encode() in res.data
