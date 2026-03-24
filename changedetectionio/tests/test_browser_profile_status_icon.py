#!/usr/bin/env python3
"""
Tests that the watchlist shows/hides the browser status icon based on the
effective browser profile, and that the system default does not bleed through
when set to 'direct_http_requests'.
"""

import pytest
from flask import url_for


def set_system_default_profile(client, profile_machine_name):
    res = client.post(
        url_for('settings_browsers.set_default'),
        data={'machine_name': profile_machine_name},
        follow_redirects=True,
    )
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# Unit tests — status_icon attribute on fetcher classes
# ---------------------------------------------------------------------------

def test_status_icon_on_browser_fetchers():
    """Browser fetcher classes must declare a status_icon dict."""
    from changedetectionio.content_fetchers.playwright import fetcher as playwright_fetcher
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

    # Inject a fake fetcher with a known status_icon — no real browser needed
    class FakeBrowserFetcher:
        status_icon = {'filename': 'test-icon.png', 'alt': 'Test browser', 'title': 'Test browser'}

    monkeypatch.setattr(content_fetchers, 'html_fake_browser', FakeBrowserFetcher, raising=False)

    # Import the filter function directly and call it inside an app context
    from changedetectionio.flask_app import app
    with app.test_request_context('/'):
        from changedetectionio.flask_app import _jinja2_filter_fetcher_status_icons
        result = _jinja2_filter_fetcher_status_icons('html_fake_browser')
        assert 'test-icon.png' in result
        assert 'Test browser' in result

    # Requests fetcher → empty string
    with app.test_request_context('/'):
        result = _jinja2_filter_fetcher_status_icons('html_requests')
        assert result == ''


# ---------------------------------------------------------------------------
# Integration tests — watchlist HTML output
# ---------------------------------------------------------------------------

def test_chrome_icon_shown_for_browser_profile(client, live_server, measure_memory_usage, datastore_path):
    """Watch explicitly set to browser_chromeplaywright should show the chrome icon."""
    datastore = client.application.config.get('DATASTORE')
    set_system_default_profile(client, 'direct_http_requests')

    uuid = datastore.add_watch(url='http://example.com', extras={'browser_profile': 'browser_chromeplaywright', 'paused': True})
    res = client.get(url_for('watchlist.index'), follow_redirects=True)
    assert b'Using a Chrome browser' in res.data, \
        "Chrome icon should appear when watch is set to browser_chromeplaywright"
    datastore.delete(uuid)


def test_no_icon_for_requests_profile(client, live_server, measure_memory_usage, datastore_path):
    """Watch explicitly set to direct_http_requests should not show the chrome icon."""
    datastore = client.application.config.get('DATASTORE')
    set_system_default_profile(client, 'direct_http_requests')

    uuid = datastore.add_watch(url='http://example.com', extras={'browser_profile': 'direct_http_requests', 'paused': True})
    res = client.get(url_for('watchlist.index'), follow_redirects=True)
    assert b'Using a Chrome browser' not in res.data, \
        "Chrome icon should NOT appear when watch is set to direct_http_requests"
    datastore.delete(uuid)


def test_no_icon_when_system_default_is_requests(client, live_server, measure_memory_usage, datastore_path):
    """Watch using system default, system default = requests → no chrome icon."""
    datastore = client.application.config.get('DATASTORE')
    set_system_default_profile(client, 'direct_http_requests')

    uuid = datastore.add_watch(url='http://example.com', extras={'paused': True})  # browser_profile=None → system default
    res = client.get(url_for('watchlist.index'), follow_redirects=True)
    assert b'Using a Chrome browser' not in res.data, \
        "Chrome icon should NOT appear when system default is requests and watch uses system default"
    datastore.delete(uuid)


def test_icon_when_system_default_is_browser(client, live_server, measure_memory_usage, datastore_path):
    """Watch using system default, system default = browser_chromeplaywright → chrome icon shown."""
    datastore = client.application.config.get('DATASTORE')
    set_system_default_profile(client, 'browser_chromeplaywright')

    uuid = datastore.add_watch(url='http://example.com', extras={'paused': True})  # browser_profile=None → system default
    res = client.get(url_for('watchlist.index'), follow_redirects=True)
    assert b'Using a Chrome browser' in res.data, \
        "Chrome icon should appear when system default is browser_chromeplaywright and watch uses system default"

    set_system_default_profile(client, 'direct_http_requests')
    datastore.delete(uuid)


def test_icon_shown_for_custom_browser_profile(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    """Custom browser profile using webdriver fetcher should also show chrome icon."""
    from changedetectionio import content_fetchers
    from changedetectionio.content_fetchers.playwright import fetcher as playwright_fetcher

    # Force html_webdriver to be the playwright class regardless of env
    monkeypatch.setattr(content_fetchers, 'html_webdriver', playwright_fetcher)

    datastore = client.application.config.get('DATASTORE')
    set_system_default_profile(client, 'direct_http_requests')

    # Create a custom profile that uses webdriver
    res = client.post(
        url_for('settings_browsers.save'),
        data={
            'name': 'My Custom Chrome',
            'fetch_backend': 'webdriver',
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

    uuid = datastore.add_watch(url='http://example.com', extras={'browser_profile': 'my_custom_chrome', 'paused': True})
    res = client.get(url_for('watchlist.index'), follow_redirects=True)
    assert b'Using a Chrome browser' in res.data, \
        "Chrome icon should appear for a custom webdriver browser profile"

    datastore.delete(uuid)
    client.get(url_for('settings_browsers.delete', machine_name='my_custom_chrome'), follow_redirects=True)
