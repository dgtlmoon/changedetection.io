#!/usr/bin/env python3

import os
import pytest
from flask import url_for
from .util import wait_for_all_checks


def get_test_url():
    """Get the test URL with proper hostname replacement for containers"""
    test_url = url_for('test_block_assets_endpoint', _external=True)
    test_url = test_url.replace('localhost.localdomain', 'cdio')
    test_url = test_url.replace('localhost', 'cdio')
    return test_url


def add_watch_and_check(client, live_server, backend, block_assets=False):
    """Add a watch with specified backend and asset blocking setting, then run check"""
    test_url = get_test_url()
    
    # Add watch
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": '', 'watch_submit_button': 'Watch'},
        follow_redirects=True
    )
    assert b"Watch added" in res.data
    
    # Configure the watch
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "url": test_url,
            "tags": "",
            'fetch_backend': backend,
            'block_assets': "y" if block_assets else "",
            "time_between_check_use_default": "y",
        },
        follow_redirects=True
    )
    assert b"Updated watch" in res.data
    
    # Trigger check
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    
    # Verify the watch was fetched successfully
    uuid = "first"
    assert live_server.app.config['DATASTORE'].data['watching'][uuid].history_n >= 1
    
    # Verify page content
    res = client.get(
        url_for("ui.ui_preview.preview_page", uuid=uuid),
        follow_redirects=True
    )
    assert b'Test page with images' in res.data
    assert b'Some text content for verification' in res.data


# SELENIUM TESTS
@pytest.mark.skipif(os.getenv('WEBDRIVER_URL') is None, reason="Needs WEBDRIVER_URL set for this test")
def test_selenium_with_block_assets(client, live_server, measure_memory_usage, datastore_path):
    """Test Selenium WebDriver with asset blocking enabled"""
    add_watch_and_check(client, live_server, 'html_webdriver', block_assets=True)


@pytest.mark.skipif(os.getenv('WEBDRIVER_URL') is None, reason="Needs WEBDRIVER_URL set for this test")
def test_selenium_without_block_assets(client, live_server, measure_memory_usage, datastore_path):
    """Test Selenium WebDriver with asset blocking disabled"""
    add_watch_and_check(client, live_server, 'html_webdriver', block_assets=False)


# PYPPETEER TESTS
@pytest.mark.skipif(os.getenv('PLAYWRIGHT_DRIVER_URL') is None, reason="Needs PLAYWRIGHT_DRIVER_URL set for this test")
def test_pyppeteer_with_block_assets(client, live_server, measure_memory_usage, datastore_path):
    """Test Pyppeteer with asset blocking enabled"""
    # Set flag to use pyppeteer instead of playwright
    os.environ['FAST_PUPPETEER_CHROME_FETCHER'] = 'True'
    try:
        add_watch_and_check(client, live_server, 'html_webdriver', block_assets=True)
    finally:
        # Clean up
        if 'FAST_PUPPETEER_CHROME_FETCHER' in os.environ:
            del os.environ['FAST_PUPPETEER_CHROME_FETCHER']


@pytest.mark.skipif(os.getenv('PLAYWRIGHT_DRIVER_URL') is None, reason="Needs PLAYWRIGHT_DRIVER_URL set for this test")
def test_pyppeteer_without_block_assets(client, live_server, measure_memory_usage, datastore_path):
    """Test Pyppeteer with asset blocking disabled"""
    # Set flag to use pyppeteer instead of playwright
    os.environ['FAST_PUPPETEER_CHROME_FETCHER'] = 'True'
    try:
        add_watch_and_check(client, live_server, 'html_webdriver', block_assets=False)
    finally:
        # Clean up
        if 'FAST_PUPPETEER_CHROME_FETCHER' in os.environ:
            del os.environ['FAST_PUPPETEER_CHROME_FETCHER']


# PLAYWRIGHT TESTS
@pytest.mark.skipif(os.getenv('PLAYWRIGHT_DRIVER_URL') is None, reason="Needs PLAYWRIGHT_DRIVER_URL set for this test")
def test_playwright_with_block_assets(client, live_server, measure_memory_usage, datastore_path):
    """Test Playwright with asset blocking enabled"""
    add_watch_and_check(client, live_server, 'html_webdriver', block_assets=True)


@pytest.mark.skipif(os.getenv('PLAYWRIGHT_DRIVER_URL') is None, reason="Needs PLAYWRIGHT_DRIVER_URL set for this test")
def test_playwright_without_block_assets(client, live_server, measure_memory_usage, datastore_path):
    """Test Playwright with asset blocking disabled"""
    add_watch_and_check(client, live_server, 'html_webdriver', block_assets=False)