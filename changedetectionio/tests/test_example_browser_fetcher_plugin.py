#!/usr/bin/env python3
"""The example_browser_fetcher example plugin (example_plugins/fetcher/example_browser_fetcher): register_content_fetcher
adds a fetcher that gets pages through its own API (here the test server), plugin_settings_tab gives it a
settings tab for the API URL and key, and fetcher_status_icon + plugin_static_path give it an icon."""
import json
import os
from urllib.parse import quote

import pytest
from flask import url_for

from .util import wait_for_all_checks, delete_all_watches, import_example_plugin, clear_plugin_discovery_caches


@pytest.fixture
def example_browser_fetcher_plugin(live_server):
    from changedetectionio import content_fetchers
    from changedetectionio.pluggy_interface import plugin_manager

    plugin = import_example_plugin('fetcher/example_browser_fetcher', 'cdio_example_browser_fetcher')
    plugin_manager.register(plugin, 'cdio_example_browser_fetcher')
    # What changedetection.io does at startup: collect plugin fetchers, inject the datastore
    content_fetchers._plugin_fetchers.update(content_fetchers.get_plugin_fetchers())
    plugin.datastore = live_server.app.config['DATASTORE']
    clear_plugin_discovery_caches()
    yield plugin
    plugin.datastore = None
    content_fetchers._plugin_fetchers.pop(plugin.FETCHER_NAME, None)
    delattr(content_fetchers, plugin.FETCHER_NAME)
    plugin_manager.unregister(plugin)
    clear_plugin_discovery_caches()


def test_example_browser_fetcher_plugin(client, live_server, measure_memory_usage, datastore_path, example_browser_fetcher_plugin):
    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')
    headers = {'content-type': 'application/json', 'x-api-key': api_key}

    # The settings tab, and the plugin listed under Settings > Info
    res = client.get(url_for("settings.settings_page"))
    assert b'Example browser fetcher' in res.data
    assert b'name="example_browser_fetcher_url"' in res.data
    assert b'<li><strong>cdio_example_browser_fetcher</strong> - Example plugin - an extra browser fetcher' in res.data

    # Save the settings through the settings page, the "API" echoes the request headers back
    res = client.post(url_for("settings.settings_page"), data={
        "requests-time_between_check-minutes": 180,
        "application-fetch_backend": "html_requests",
        "example_browser_fetcher_url": url_for('test_headers', _external=True) + '?url={url}',
        "example_browser_fetcher_key": "secret-key-123",
    }, follow_redirects=True)
    assert b"Settings updated." in res.data
    with open(os.path.join(datastore_path, 'cdio_example_browser_fetcher.json')) as f:
        assert json.load(f)['example_browser_fetcher_key'] == 'secret-key-123'

    watch_url = 'https://example.com/product?id=1'
    res = client.post(url_for("createwatch"), headers=headers,
                      data=json.dumps({"url": watch_url, "fetch_backend": "html_example_browser_fetcher"}))
    assert res.status_code == 201, res.data
    uuid = res.json.get('uuid')
    wait_for_all_checks(client)

    # Installed fetchers are accepted in 'fetch_backend', unknown ones still aren't
    res = client.post(url_for("createwatch"), headers=headers,
                      data=json.dumps({"url": watch_url, "fetch_backend": "html_no_such_fetcher"}))
    assert res.status_code == 400

    # Fetched through the API, which got the key in the X-Api-Key header
    res = client.get(url_for("watchsinglehistory", uuid=uuid, timestamp='latest'), headers=headers)
    assert res.status_code == 200, "The check should have fetched through the plugin's API"
    assert b'X-Api-Key:secret-key-123' in res.data

    # The fetcher's screenshot (random noise) is saved and served as a valid PNG
    import struct
    res = client.get(url_for('static_content', group='screenshot', filename=uuid))
    assert res.status_code == 200
    assert res.data.startswith(b'\x89PNG\r\n\x1a\n') and res.data[12:16] == b'IHDR'
    assert struct.unpack('>II', res.data[16:24]) == (240, 160)

    # The status icon in the watch list, served from the plugin's static directory
    res = client.get(url_for("watchlist.index"))
    assert b'/static/plugin/cdio_example_browser_fetcher.svg' in res.data
    assert client.get('/static/plugin/cdio_example_browser_fetcher.svg').status_code == 200

    # The watch URL is passed to the API URL-encoded
    from changedetectionio.pluggy_interface import save_plugin_settings
    save_plugin_settings(datastore_path, 'cdio_example_browser_fetcher',
                         {"example_browser_fetcher_url": url_for('test_return_query', _external=True) + '?url={url}'})
    client.get(url_for("watch", uuid=uuid, recheck=1), headers=headers)
    wait_for_all_checks(client)
    res = client.get(url_for("watchsinglehistory", uuid=uuid, timestamp='latest'), headers=headers)
    assert quote(watch_url, safe='').encode() in res.data

    delete_all_watches(client)
