#!/usr/bin/env python3
"""
Tests that the watchlist shows/hides the browser status icon based on the
effective browser profile, covering the full inheritance chain:

  watch browser_profile → system default browser_profile → direct_http_requests
"""

import pytest
from flask import url_for


def set_system_default_profile(client, profile_machine_name):
    res = client.post(
        url_for('settings.settings_browsers.set_default'),
        data={'machine_name': profile_machine_name},
        follow_redirects=True,
    )
    assert res.status_code == 200


def create_custom_browser_profile(client, name='My Custom Chrome'):
    """Create a custom browser profile using playwright_cdp and return its machine name."""
    res = client.post(
        url_for('settings.settings_browsers.save'),
        data={
            'name': name,
            'fetch_backend': 'playwright_cdp',
            'browser_connection_url': 'ws://localhost:3000',
            'viewport_width': 1280,
            'viewport_height': 1000,
            'block_images': '',
            'block_fonts': '',
            'ignore_https_errors': '',
            'user_agent': '',
            'locale': '',
            'custom_headers': '',
            'original_machine_name': '',
        },
        follow_redirects=True,
    )
    assert b'saved.' in res.data
    from changedetectionio.model.browser_profile import BrowserProfile
    return BrowserProfile(name=name, fetch_backend='playwright_cdp').get_machine_name()


def create_requests_browser_profile(client, name, user_agent='', custom_headers=''):
    """Create a requests-type browser profile with optional UA and custom headers."""
    res = client.post(
        url_for('settings.settings_browsers.save'),
        data={
            'name': name,
            'fetch_backend': 'requests',
            'browser_connection_url': '',
            'viewport_width': 1280,
            'viewport_height': 1000,
            'block_images': '',
            'block_fonts': '',
            'ignore_https_errors': '',
            'user_agent': user_agent,
            'locale': '',
            'custom_headers': custom_headers,
            'original_machine_name': '',
        },
        follow_redirects=True,
    )
    assert b'saved.' in res.data
    from changedetectionio.model.browser_profile import BrowserProfile
    return BrowserProfile(name=name, fetch_backend='requests').get_machine_name()


# ---------------------------------------------------------------------------
# Unit tests — status_icon attribute on fetcher classes
# ---------------------------------------------------------------------------

def test_status_icon_on_browser_fetchers():
    """Browser fetcher classes must declare a status_icon dict."""
    from changedetectionio.content_fetchers.playwright.CDP import fetcher as playwright_fetcher
    from changedetectionio.content_fetchers.puppeteer import fetcher as puppeteer_fetcher
    from changedetectionio.content_fetchers.webdriver_selenium import fetcher as selenium_fetcher

    for cls in (playwright_fetcher, puppeteer_fetcher, selenium_fetcher):
        assert cls.status_icon is not None, f"{cls} should have status_icon set"
        assert 'filename' in cls.status_icon
        assert 'alt' in cls.status_icon
        assert 'title' in cls.status_icon


def test_no_status_icon_on_requests_fetcher():
    """The plain requests fetcher must have status_icon = None."""
    from changedetectionio.content_fetchers.requests import fetcher as requests_fetcher
    assert requests_fetcher.status_icon is None


def test_fetcher_status_icons_filter_uses_status_icon(monkeypatch):
    """fetcher_status_icons filter returns icon HTML for a class with status_icon set."""
    from changedetectionio import content_fetchers

    class FakeBrowserFetcher:
        status_icon = {'filename': 'test-icon.png', 'alt': 'Test browser', 'title': 'Test browser'}
        supports_screenshots = True

    monkeypatch.setitem(content_fetchers.FETCHERS, 'fake_browser', FakeBrowserFetcher)

    from changedetectionio.flask_app import app
    with app.test_request_context('/'):
        from changedetectionio.flask_app import _jinja2_filter_fetcher_status_icons
        result = _jinja2_filter_fetcher_status_icons('fake_browser')
        assert 'test-icon.png' in result
        assert 'Test browser' in result

    # Requests fetcher → empty string
    with app.test_request_context('/'):
        result = _jinja2_filter_fetcher_status_icons('requests')
        assert result == ''


# ---------------------------------------------------------------------------
# Integration tests — inheritance chain
# ---------------------------------------------------------------------------

def test_watch_explicit_browser_profile_shows_icon(client, live_server, measure_memory_usage, datastore_path):
    """Watch explicitly assigned a browser profile shows the chrome icon,
    even when the system default is requests."""
    datastore = client.application.config.get('DATASTORE')
    set_system_default_profile(client, 'direct_http_requests')

    machine_name = create_custom_browser_profile(client)
    uuid = datastore.add_watch(url='http://example.com', extras={'browser_profile': machine_name, 'paused': True})
    res = client.get(url_for('watchlist.index'), follow_redirects=True)
    assert b'Using a Chrome browser' in res.data, \
        "Chrome icon should appear when watch is explicitly set to a browser profile"

    datastore.delete(uuid)
    client.get(url_for('settings.settings_browsers.delete', machine_name=machine_name), follow_redirects=True)


def test_watch_explicit_requests_profile_no_icon(client, live_server, measure_memory_usage, datastore_path):
    """Watch explicitly set to direct_http_requests never shows the chrome icon,
    even when the system default is a browser."""
    datastore = client.application.config.get('DATASTORE')

    machine_name = create_custom_browser_profile(client)
    set_system_default_profile(client, machine_name)

    uuid = datastore.add_watch(url='http://example.com', extras={'browser_profile': 'direct_http_requests', 'paused': True})
    res = client.get(url_for('watchlist.index'), follow_redirects=True)
    assert b'Using a Chrome browser' not in res.data, \
        "Chrome icon should NOT appear when watch is explicitly set to direct_http_requests"

    datastore.delete(uuid)
    set_system_default_profile(client, 'direct_http_requests')
    client.get(url_for('settings.settings_browsers.delete', machine_name=machine_name), follow_redirects=True)


def test_system_default_requests_inherited_by_watch(client, live_server, measure_memory_usage, datastore_path):
    """Watch using system default inherits requests → no icon."""
    datastore = client.application.config.get('DATASTORE')
    set_system_default_profile(client, 'direct_http_requests')

    uuid = datastore.add_watch(url='http://example.com', extras={'paused': True})
    res = client.get(url_for('watchlist.index'), follow_redirects=True)
    assert b'Using a Chrome browser' not in res.data, \
        "Chrome icon should NOT appear when system default is requests and watch uses system default"

    datastore.delete(uuid)


def test_system_default_browser_inherited_by_watch(client, live_server, measure_memory_usage, datastore_path):
    """Watch using system default inherits a browser profile → icon shown."""
    datastore = client.application.config.get('DATASTORE')

    machine_name = create_custom_browser_profile(client)
    set_system_default_profile(client, machine_name)

    uuid = datastore.add_watch(url='http://example.com', extras={'paused': True})
    res = client.get(url_for('watchlist.index'), follow_redirects=True)
    assert b'Using a Chrome browser' in res.data, \
        "Chrome icon should appear when system default is a browser profile and watch uses system default"

    datastore.delete(uuid)
    set_system_default_profile(client, 'direct_http_requests')
    client.get(url_for('settings.settings_browsers.delete', machine_name=machine_name), follow_redirects=True)

# ---------------------------------------------------------------------------
# Integration tests — BrowserProfile UA and custom_headers applied to requests
# ---------------------------------------------------------------------------

def test_browser_profile_user_agent_applied(client, live_server, measure_memory_usage, datastore_path):
    """User-Agent set on a BrowserProfile appears in the fetched request;
    a per-watch User-Agent header overrides it."""
    from changedetectionio.tests.util import wait_for_all_checks

    datastore = client.application.config.get('DATASTORE')
    test_url = url_for('test_headers', _external=True)

    machine_name = create_requests_browser_profile(
        client, name='UA Profile Test', user_agent='profile-ua/2.0'
    )

    uuid = datastore.add_watch(url=test_url, extras={'browser_profile': machine_name})
    client.get(url_for('ui.form_watch_checknow'), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.get(url_for('ui.ui_preview.preview_page', uuid='first'), follow_redirects=True)
    assert b'profile-ua/2.0' in res.data, "Profile UA should appear in the echoed request headers"

    # Per-watch User-Agent header overrides the profile UA
    client.post(
        url_for('ui.ui_edit.edit_page', uuid='first'),
        data={
            'url': test_url,
            'tags': '',
            'browser_profile': machine_name,
            'headers': 'User-Agent: watch-ua/3.0',
            'time_between_check_use_default': 'y',
        },
        follow_redirects=True,
    )
    client.get(url_for('ui.form_watch_checknow'), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.get(url_for('ui.ui_preview.preview_page', uuid='first'), follow_redirects=True)
    assert b'watch-ua/3.0' in res.data, "Watch-level UA should override profile UA"
    assert b'profile-ua/2.0' not in res.data, "Profile UA should be superseded by watch-level header"

    datastore.delete(uuid)
    client.get(url_for('settings.settings_browsers.delete', machine_name=machine_name), follow_redirects=True)


def test_browser_profile_custom_headers_applied(client, live_server, measure_memory_usage, datastore_path):
    """Custom headers set on a BrowserProfile are sent with every request using that profile;
    per-watch headers override them when the same header name is used."""
    from changedetectionio.tests.util import wait_for_all_checks

    datastore = client.application.config.get('DATASTORE')
    test_url = url_for('test_headers', _external=True)

    machine_name = create_requests_browser_profile(
        client,
        name='Headers Profile Test',
        custom_headers='X-Profile-Header: profile-value\nX-Shared-Header: from-profile',
    )

    uuid = datastore.add_watch(url=test_url, extras={'browser_profile': machine_name})
    client.get(url_for('ui.form_watch_checknow'), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.get(url_for('ui.ui_preview.preview_page', uuid='first'), follow_redirects=True)
    assert b'X-Profile-Header:profile-value' in res.data, \
        "Profile custom header should appear in the echoed request"
    assert b'X-Shared-Header:from-profile' in res.data, \
        "Second profile custom header should appear"

    # Per-watch header for the same key overrides the profile header
    client.post(
        url_for('ui.ui_edit.edit_page', uuid='first'),
        data={
            'url': test_url,
            'tags': '',
            'browser_profile': machine_name,
            'headers': 'X-Shared-Header: from-watch\nX-Watch-Only: watch-value',
            'time_between_check_use_default': 'y',
        },
        follow_redirects=True,
    )
    client.get(url_for('ui.form_watch_checknow'), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.get(url_for('ui.ui_preview.preview_page', uuid='first'), follow_redirects=True)
    assert b'X-Profile-Header:profile-value' in res.data, \
        "Unrelated profile header should still be present"
    assert b'X-Shared-Header:from-watch' in res.data, \
        "Watch-level header should override the same-named profile header"
    assert b'X-Shared-Header:from-profile' not in res.data, \
        "Profile value for overridden header should be gone"
    assert b'X-Watch-Only:watch-value' in res.data, \
        "Watch-only header should appear"

    datastore.delete(uuid)
    client.get(url_for('settings.settings_browsers.delete', machine_name=machine_name), follow_redirects=True)
