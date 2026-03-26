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
            'original_machine_name': '',
        },
        follow_redirects=True,
    )
    assert b'saved.' in res.data
    from changedetectionio.model.browser_profile import BrowserProfile
    return BrowserProfile(name=name, fetch_backend='playwright_cdp').get_machine_name()


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
