#!/usr/bin/env python3
"""The fallback_fetcher example plugin (example_plugins/fetcher/fallback_fetcher): a fetcher that gets pages from a
scraping API (here the test server's /test-scrape-api), used either as a watch's fetch method or, through the
select_fetch_backend hook, only when the normal fetch gets a status code such as 403. While a watch is "under control"
of the plugin, recheck_seconds_override gives it a longer recheck time and watch_list_extra_text says so. A daily
limit on successful calls is kept in the plugin's own state file, and a "Fetch stats" page (register_blueprints,
register_sidebar_items) shows it."""
import asyncio
import json
import os

import pytest
from flask import url_for

from .util import wait_for_all_checks, delete_all_watches, import_example_plugin, clear_plugin_discovery_caches


@pytest.fixture
def fallback_fetcher_plugin(live_server):
    from changedetectionio import content_fetchers
    from changedetectionio.pluggy_interface import plugin_manager, register_plugin_blueprints

    plugin = import_example_plugin('fetcher/fallback_fetcher', 'cdio_example_fallback_fetcher')
    plugin_manager.register(plugin, 'cdio_example_fallback_fetcher')
    app = live_server.app
    if plugin.PLUGIN_ID not in app.blueprints:
        # The app is shared by the whole test session and has already served requests, after which
        # Flask refuses new blueprints. At real startup the hook runs before the first request.
        got_first_request = app._got_first_request
        app._got_first_request = False
        try:
            register_plugin_blueprints(app, app.config['DATASTORE'])
        finally:
            app._got_first_request = got_first_request
    # What changedetection.io does at startup: collect plugin fetchers, inject the datastore
    content_fetchers._plugin_fetchers.update(content_fetchers.get_plugin_fetchers())
    plugin.datastore = live_server.app.config['DATASTORE']
    plugin.under_control.clear()
    from cdio_example_fallback_fetcher import state
    state.reset()
    clear_plugin_discovery_caches()
    yield plugin
    state.reset()
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
                'fallback_fetcher_groups': '', 'fallback_fetcher_control_hours': 24,
                'fallback_fetcher_recheck': {'weeks': None, 'days': None, 'hours': 12, 'minutes': None, 'seconds': None},
                'fallback_fetcher_daily_limit': 0}
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
    from changedetectionio.pluggy_interface import apply_recheck_seconds_override, select_fetch_backends
    plugin = fallback_fetcher_plugin
    datastore = live_server.app.config['DATASTORE']

    # The settings tab, with the same recheck time widget as everywhere else
    res = client.get(url_for("settings.settings_page"))
    assert b'Fallback fetcher' in res.data
    assert b'name="fallback_fetcher_status_codes"' in res.data
    assert b'class="time-check-widget" id="fallback_fetcher_recheck"' in res.data
    assert b'name="fallback_fetcher_recheck-hours"' in res.data

    # Saved through the settings page, the widget's parts come back as a dict
    res = client.post(url_for("settings.settings_page"), data={
        "requests-time_between_check-minutes": 180,
        "application-fetch_backend": "html_requests",
        "fallback_fetcher_url": url_for('test_scrape_api', _external=True),
        "fallback_fetcher_status_codes": "403, 429",
        "fallback_fetcher_control_hours": 24,
        "fallback_fetcher_recheck-days": 1,
        "fallback_fetcher_recheck-hours": 2,
    }, follow_redirects=True)
    assert b"Settings updated." in res.data
    with open(os.path.join(datastore_path, 'cdio_example_fallback_fetcher.json')) as f:
        saved = json.load(f)
    assert saved['fallback_fetcher_recheck']['days'] == 1 and saved['fallback_fetcher_recheck']['hours'] == 2
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
    # And on the fetch stats page, reached from its sidebar icon
    stats_url = url_for('cdio_example_fallback_fetcher.fetch_stats')
    res = client.get(url_for("watchlist.index"))
    assert f'href="{stats_url}"'.encode() in res.data
    res = client.get(stats_url)
    assert res.status_code == 200
    assert b'<strong>1</strong> successful calls in the last 24 hours' in res.data
    assert b'<td>HTTP 403</td>' in res.data and b'<td>12h</td>' in res.data
    assert b'#plugin-cdio_example_fallback_fetcher' in res.data, "Links to its settings tab"
    # Overdue counts the overridden recheck time too
    from changedetectionio.api.SystemInfo import overdue_watch_uuids
    watch['last_checked'] = int(__import__('time').time()) - 3600
    assert uuid not in overdue_watch_uuids(datastore)

    # While under control, checks go straight to the fallback, the site isn't asked (it would answer 200 now)
    assert asyncio.run(select_fetch_backends(watch, datastore, 'html_requests')) == [plugin.FETCHER_NAME]
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


def test_fallback_fetcher_daily_limit(client, live_server, measure_memory_usage, datastore_path, fallback_fetcher_plugin):
    """Successful calls are counted in the plugin's own state file, over the limit the check fails without calling the API."""
    import re
    from cdio_example_fallback_fetcher import state
    datastore = live_server.app.config['DATASTORE']
    _settings(datastore_path, fallback_fetcher_daily_limit=1)

    uuid = datastore.add_watch(url='https://example.com/limited', extras={'fetch_backend': fallback_fetcher_plugin.FETCHER_NAME})
    wait_for_all_checks(client)
    watch = datastore.data['watching'][uuid]
    assert not watch.get('last_error')
    with open(os.path.join(datastore_path, 'cdio_example_fallback_fetcher-state.json')) as f:
        assert len(json.load(f)['successful_calls']) == 1

    # Second check: over the limit, an error saying when it can go again, and no call made
    _recheck(client, uuid)
    # About a day from the call (23h or 1d depending on the second it's worked out in)
    assert re.search(r'Fallback fetcher limit reached, 1 successful calls in 24 hours, the next is possible in (23h|1d)',
                     str(watch.get('last_error'))), watch.get('last_error')
    assert len(state.calls_in_window()) == 1
    res = client.get(url_for('cdio_example_fallback_fetcher.fetch_stats'))
    assert b'<strong>1</strong> / 1 successful calls' in res.data and b'Limit reached' in res.data

    # Read back from the file after a restart, calls older than 24 hours no longer count
    with open(os.path.join(datastore_path, 'cdio_example_fallback_fetcher-state.json'), 'w') as f:
        json.dump({'successful_calls': [__import__('time').time() - 25 * 3600]}, f)
    state.reset()
    assert state.calls_in_window() == []
    _recheck(client, uuid)
    assert not watch.get('last_error')

    delete_all_watches(client)


SECOND = 'html_test_second_fallback'


class SecondFallback:
    """A second fallback plugin, to chain with the example: offers itself when the watch's own fetch got a 403, or
    further down the chain, at its own priority."""
    priority = 20
    fail = False
    calls = 0

    from changedetectionio.plugin_api import hookimpl as _hookimpl

    @_hookimpl
    def select_fetch_backend(self, watch, datastore, backend_name, failed_fetch, tried):
        if failed_fetch is None or SECOND in tried:
            return None
        if len(tried) == 1 and getattr(failed_fetch, 'status_code', None) != 403:
            return None
        return {'backend': SECOND, 'priority': self.priority}


def _second_fetcher_class(plugin):
    from changedetectionio.plugin_api import Fetcher

    class second_fetcher(Fetcher):
        fetcher_description = 'Second fallback (test)'

        def __init__(self, proxy_override=None, custom_browser_connection_url=None, **kwargs):
            super().__init__(**kwargs)

        async def run(self, url=None, **kwargs):
            plugin.calls += 1
            if plugin.fail:
                raise Exception('The second fallback failed too')
            self.status_code = 200
            self.content = '<html><body><p>Fetched by the second fallback</p></body></html>'
            self.raw_content = self.content.encode()
            self.headers = {'content-type': 'text/html'}

        async def quit(self, watch=None):
            pass

        def get_last_status_code(self):
            return self.status_code

        def screenshot_step(self, step_n):
            return None

        def is_ready(self):
            return True

    return second_fetcher


@pytest.fixture
def second_fallback(fallback_fetcher_plugin):
    from changedetectionio import content_fetchers
    from changedetectionio.pluggy_interface import plugin_manager
    plugin = SecondFallback()
    fetcher_class = _second_fetcher_class(plugin)
    setattr(content_fetchers, SECOND, fetcher_class)
    content_fetchers._plugin_fetchers[SECOND] = fetcher_class
    plugin_manager.register(plugin, 'test_second_fallback')
    yield plugin
    plugin_manager.unregister(plugin)
    content_fetchers._plugin_fetchers.pop(SECOND, None)
    delattr(content_fetchers, SECOND)


def test_fallback_fetchers_chain_in_priority_order(client, live_server, measure_memory_usage, datastore_path,
                                                   fallback_fetcher_plugin, second_fallback):
    import time
    from cdio_example_fallback_fetcher import state
    example = fallback_fetcher_plugin
    datastore = live_server.app.config['DATASTORE']
    broken_api = url_for('test_scrape_api', _external=True) + '-missing'

    # The example (priority 10) comes first, its API fails, so the second (priority 20) takes it, same check
    _settings(datastore_path, fallback_fetcher_url=broken_api)
    uuid = datastore.add_watch(url=url_for('test_endpoint', status_code=403, content='Access Denied', _external=True))
    watch = datastore.data['watching'][uuid]
    wait_for_all_checks(client)
    assert not watch.get('last_error'), watch.get('last_error')
    assert b'Fetched by the second fallback' in _latest(client, uuid)
    assert second_fallback.calls == 1
    assert uuid not in example.under_control, "The example failed, so it didn't take the watch over"

    # The example is over its daily limit: not even offered, the second goes straight away, no call to the API
    _settings(datastore_path, fallback_fetcher_daily_limit=1)
    state.record_successful_call()
    _recheck(client, uuid)
    assert not watch.get('last_error'), watch.get('last_error')
    assert second_fallback.calls == 2
    assert len(state.calls_in_window()) == 1

    # Back under its limit and working: the example wins on priority, and takes the watch over
    with open(os.path.join(datastore_path, 'cdio_example_fallback_fetcher-state.json'), 'w') as f:
        json.dump({'successful_calls': [time.time() - 25 * 3600]}, f)
    state.reset()
    _settings(datastore_path)
    _recheck(client, uuid)
    assert b'Fetched by the scraping API' in _latest(client, uuid)
    assert second_fallback.calls == 2
    assert example.under_control[uuid]['status_code'] == 403

    # Priority decides: the second at 5 comes before the example at 10
    example.under_control.clear()
    second_fallback.priority = 5
    _recheck(client, uuid)
    assert b'Fetched by the second fallback' in _latest(client, uuid)
    assert second_fallback.calls == 3

    # Everything fails: the last fallback's error is what the watch shows (second at 5, then the example at 10)
    second_fallback.fail = True
    _settings(datastore_path, fallback_fetcher_url=broken_api)
    _recheck(client, uuid)
    assert 'Scraping API returned HTTP 4' in str(watch.get('last_error')), watch.get('last_error')
    assert second_fallback.calls == 4

    delete_all_watches(client)


def test_fallback_fetcher_recheck_minimum_from_env(client, live_server, measure_memory_usage, datastore_path,
                                                  fallback_fetcher_plugin, monkeypatch):
    """EXAMPLE_FETCHER_HELLOWORLD_TIME_BETWEEN_RECHECK_MINIMUM_SECONDS fixes the minimum recheck time: the widget shows
    it read-only, and it wins over the saved setting."""
    import re
    from changedetectionio.pluggy_interface import apply_recheck_seconds_override
    monkeypatch.setenv('EXAMPLE_FETCHER_HELLOWORLD_TIME_BETWEEN_RECHECK_MINIMUM_SECONDS', '7200')
    datastore = live_server.app.config['DATASTORE']
    _settings(datastore_path)  # saved: 12 hours

    html = client.get(url_for("settings.settings_page")).get_data(as_text=True)
    seconds_input = re.search(r'<input[^>]*id="fallback_fetcher_recheck-seconds"[^>]*>', html).group(0)
    assert 'disabled' in seconds_input and 'readonly' in seconds_input and 'value="7200"' in seconds_input
    hours_input = re.search(r'<input[^>]*id="fallback_fetcher_recheck-hours"[^>]*>', html).group(0)
    assert 'disabled' in hours_input and 'value="12"' not in hours_input
    assert 'Set to 7200 seconds by the EXAMPLE_FETCHER_HELLOWORLD_TIME_BETWEEN_RECHECK_MINIMUM_SECONDS environment variable.' in html

    uuid = datastore.add_watch(url=url_for('test_endpoint', status_code=403, content='Access Denied', _external=True))
    wait_for_all_checks(client)
    watch = datastore.data['watching'][uuid]
    assert fallback_fetcher_plugin.under_control[uuid]['recheck_seconds'] == 7200
    assert apply_recheck_seconds_override(watch, datastore, 1800) == 7200
    assert b'checked no more often than every 2h' in client.get(url_for("watchlist.index")).data

    delete_all_watches(client)
