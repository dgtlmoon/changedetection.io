#!/usr/bin/env python3
"""The fallback_fetcher example plugin (example_plugins/fetcher/fallback_fetcher): a fetcher that gets pages from a
scraping API (here the test server's /test-scrape-api), used either as a watch's fetch method or, through the
select_fetch_backend hook, only when the normal fetch gets a status code such as 403. While a watch is "under control"
of the plugin, recheck_seconds_override gives it a longer recheck time and watch_list_extra_text says so."""
import asyncio
import json
import os

import pytest
from flask import url_for

from .util import wait_for_all_checks, delete_all_watches, import_example_plugin, clear_plugin_discovery_caches


@pytest.fixture
def fallback_fetcher_plugin(live_server):
    from changedetectionio import content_fetchers
    from changedetectionio.pluggy_interface import plugin_manager

    plugin = import_example_plugin('fetcher/fallback_fetcher', 'cdio_example_fallback_fetcher')
    plugin_manager.register(plugin, 'cdio_example_fallback_fetcher')
    # What changedetection.io does at startup: collect plugin fetchers, inject the datastore
    content_fetchers._plugin_fetchers.update(content_fetchers.get_plugin_fetchers())
    plugin.datastore = live_server.app.config['DATASTORE']
    plugin.under_control.clear()
    clear_plugin_discovery_caches()
    yield plugin
    plugin.datastore = None
    plugin.under_control.clear()
    content_fetchers._plugin_fetchers.pop(plugin.FETCHER_NAME, None)
    delattr(content_fetchers, plugin.FETCHER_NAME)
    plugin_manager.unregister(plugin)
    clear_plugin_discovery_caches()


def _settings(datastore_path, **overrides):
    from changedetectionio.pluggy_interface import save_plugin_settings
    settings = {'fallback_fetcher_url': url_for('test_scrape_api', _external=True), 'fallback_fetcher_key': 'key-123',
                'fallback_fetcher_screenshot': True, 'fallback_fetcher_status_codes': '403, 429',
                'fallback_fetcher_groups': '', 'fallback_fetcher_control_hours': 24, 'fallback_fetcher_recheck_hours': 12}
    settings.update(overrides)
    save_plugin_settings(datastore_path, 'cdio_example_fallback_fetcher', settings)


def _latest(client, uuid):
    api_key = client.application.config['DATASTORE'].data['settings']['application'].get('api_access_token')
    return client.get(url_for("watchsinglehistory", uuid=uuid, timestamp='latest'), headers={'x-api-key': api_key}).data


def _recheck(client, uuid):
    api_key = client.application.config['DATASTORE'].data['settings']['application'].get('api_access_token')
    client.get(url_for("watch", uuid=uuid, recheck=1), headers={'x-api-key': api_key})
    wait_for_all_checks(client)


def test_fallback_fetcher_takes_over_on_403(client, live_server, measure_memory_usage, datastore_path, fallback_fetcher_plugin):
    from changedetectionio.pluggy_interface import apply_recheck_seconds_override, select_fetch_backend
    plugin = fallback_fetcher_plugin
    datastore = live_server.app.config['DATASTORE']

    # The settings tab
    res = client.get(url_for("settings.settings_page"))
    assert b'Fallback fetcher' in res.data
    assert b'name="fallback_fetcher_status_codes"' in res.data
    _settings(datastore_path)

    # The site blocks the normal fetch with a 403, the check is retried through the scraping API straight away
    uuid = datastore.add_watch(url=url_for('test_endpoint', status_code=403, content='Access Denied', _external=True))
    watch = datastore.data['watching'][uuid]
    wait_for_all_checks(client)
    assert not watch.get('last_error'), watch.get('last_error')
    latest = _latest(client, uuid)
    assert b'Fetched by the scraping API' in latest and b'key:key-123' in latest
    # And its screenshot is saved
    assert client.get(url_for('static_content', group='screenshot', filename=uuid)).data.startswith(b'\x89PNG')

    # Now under the plugin's control: 12h between checks instead of the usual, and the watch list says why
    assert plugin.under_control[uuid]['status_code'] == 403
    assert apply_recheck_seconds_override(watch, datastore, 1800) == 12 * 3600
    # It's a minimum: a watch checked less often (every 3 days) keeps its own recheck time
    assert apply_recheck_seconds_override(watch, datastore, 3 * 86400) == 3 * 86400
    assert b'Blocked with HTTP 403, using the fallback fetcher, checked no more often than every 12h for the next 24h' in client.get(url_for("watchlist.index")).data
    # Overdue counts the overridden recheck time too
    from changedetectionio.api.SystemInfo import overdue_watch_uuids
    watch['last_checked'] = int(__import__('time').time()) - 3600
    assert uuid not in overdue_watch_uuids(datastore)

    # While under control, checks go straight to the fallback, the site isn't asked (it would answer 200 now)
    assert asyncio.run(select_fetch_backend(watch, datastore, 'html_requests')) == plugin.FETCHER_NAME
    watch['url'] = url_for('test_endpoint', content='The direct page', _external=True)
    _recheck(client, uuid)
    assert b'Fetched by the scraping API' in _latest(client, uuid)

    # Control over: the normal fetch again, the normal recheck time, no note
    plugin.under_control[uuid]['until'] = 0
    _recheck(client, uuid)
    assert b'The direct page' in _latest(client, uuid)
    assert uuid not in plugin.under_control
    assert apply_recheck_seconds_override(watch, datastore, 1800) == 1800
    assert b'using the fallback fetcher' not in client.get(url_for("watchlist.index")).data

    # A status code that isn't in the list is left alone, the watch shows the error
    watch['url'] = url_for('test_endpoint', status_code=404, content='Not here', _external=True)
    _recheck(client, uuid)
    assert '404' in str(watch.get('last_error'))
    assert uuid not in plugin.under_control

    delete_all_watches(client)


def test_fallback_fetcher_only_for_its_groups(client, live_server, measure_memory_usage, datastore_path, fallback_fetcher_plugin):
    datastore = live_server.app.config['DATASTORE']
    _settings(datastore_path, fallback_fetcher_groups='Shops')

    uuid = datastore.add_watch(url=url_for('test_endpoint', status_code=403, content='Access Denied', _external=True))
    wait_for_all_checks(client)
    assert '403' in str(datastore.data['watching'][uuid].get('last_error')), "Not in the group, so no fallback"

    shop = datastore.add_watch(url=url_for('test_endpoint', status_code=403, content='Access Denied', _external=True),
                               tag='shops')
    wait_for_all_checks(client)
    assert not datastore.data['watching'][shop].get('last_error')
    assert b'Fetched by the scraping API' in _latest(client, shop)

    delete_all_watches(client)


def test_fallback_fetcher_as_fetch_method(client, live_server, measure_memory_usage, datastore_path, fallback_fetcher_plugin):
    datastore = live_server.app.config['DATASTORE']
    api_key = datastore.data['settings']['application'].get('api_access_token')
    # No fallback status codes: only used by watches that pick it
    _settings(datastore_path, fallback_fetcher_status_codes='', fallback_fetcher_screenshot=False)

    res = client.post(url_for("createwatch"), headers={'content-type': 'application/json', 'x-api-key': api_key},
                      data=json.dumps({"url": "https://example.com/page", "fetch_backend": fallback_fetcher_plugin.FETCHER_NAME}))
    assert res.status_code == 201, res.data
    uuid = res.json.get('uuid')
    wait_for_all_checks(client)
    latest = _latest(client, uuid)
    assert b'url:https://example.com/page' in latest
    assert not fallback_fetcher_plugin.under_control
    # The status icon in the watch list, served from the plugin's static directory
    assert b'/static/plugin/cdio_example_fallback_fetcher.svg' in client.get(url_for("watchlist.index")).data

    # The site's own error status, as the scraping API reports it, is the watch's error
    _settings(datastore_path, fallback_fetcher_url=url_for('test_scrape_api', status_code=500, _external=True))
    _recheck(client, uuid)
    assert '500' in str(datastore.data['watching'][uuid].get('last_error'))

    delete_all_watches(client)
