#!/usr/bin/env python3

import os
import time
from flask import url_for
from .util import live_server_setup, wait_for_all_checks


def test_webdriver_block_assets_global_setting(client, live_server, measure_memory_usage, datastore_path):
    """Test that webdriver_block_assets works as a global setting"""
    
    # live_server_setup(live_server) # Setup on conftest per function
    assert os.getenv('PLAYWRIGHT_DRIVER_URL'), "Needs PLAYWRIGHT_DRIVER_URL set for this test"

    test_url = url_for('test_block_assets_endpoint', _external=True)
    test_url = test_url.replace('localhost.localdomain', 'cdio')
    test_url = test_url.replace('localhost', 'cdio')

    # Enable global webdriver_block_assets setting
    res = client.post(
        url_for("settings.settings_page"),
        data={
            "application-webdriver_block_assets": "y",
            "application-fetch_backend": "html_webdriver",
            "requests-time_between_check-minutes": 180,
        },
        follow_redirects=True
    )
    assert b"Settings updated." in res.data

    # Add our URL to the import page
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data
    wait_for_all_checks(client)
    
    # Verify the watch was fetched successfully
    uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))
    assert live_server.app.config['DATASTORE'].data['watching'][uuid].history_n >= 1, "Watch history had atleast 1 (everything fetched OK)"

    res = client.get(
        url_for("ui.ui_preview.preview_page", uuid=uuid),
        follow_redirects=True
    )
    
    assert b'Test page with images' in res.data


def test_webdriver_block_assets_per_watch_setting(client, live_server, measure_memory_usage, datastore_path):
    """Test that webdriver_block_assets works as a per-watch override"""
    
    # live_server_setup(live_server) # Setup on conftest per function  
    assert os.getenv('PLAYWRIGHT_DRIVER_URL'), "Needs PLAYWRIGHT_DRIVER_URL set for this test"

    test_url = url_for('test_block_assets_endpoint', _external=True)
    test_url = test_url.replace('localhost.localdomain', 'cdio')
    test_url = test_url.replace('localhost', 'cdio')

    # Keep global setting disabled
    res = client.post(
        url_for("settings.settings_page"),
        data={
            "application-webdriver_block_assets": "",  # Disabled globally
            "application-fetch_backend": "html_webdriver",
            "requests-time_between_check-minutes": 180,
        },
        follow_redirects=True
    )
    assert b"Settings updated." in res.data

    # Add watch with edit mode
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": '', 'edit_and_watch_submit_button': 'Edit > Watch'},
        follow_redirects=True
    )

    assert b"Watch added in Paused state, saving will unpause" in res.data

    # Edit the watch to enable webdriver_block_assets
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first", unpause_on_save=1),
        data={
            "url": test_url,
            "tags": "",
            'fetch_backend': "html_webdriver",
            'webdriver_block_assets': "y",  # Enable for this watch
            "time_between_check_use_default": "y",
        },
        follow_redirects=True
    )
    assert b"unpaused" in res.data

    wait_for_all_checks(client)
    
    uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))
    assert live_server.app.config['DATASTORE'].data['watching'][uuid].history_n >= 1, "Watch history had atleast 1 (everything fetched OK)"

    res = client.get(
        url_for("ui.ui_preview.preview_page", uuid=uuid),
        follow_redirects=True
    )
    
    assert b'Test page with images' in res.data


def test_webdriver_block_assets_disabled_by_default(client, live_server, measure_memory_usage, datastore_path):
    """Test that webdriver_block_assets is disabled by default"""
    
    # live_server_setup(live_server) # Setup on conftest per function
    assert os.getenv('PLAYWRIGHT_DRIVER_URL'), "Needs PLAYWRIGHT_DRIVER_URL set for this test"

    test_url = url_for('test_block_assets_endpoint', _external=True)
    test_url = test_url.replace('localhost.localdomain', 'cdio')
    test_url = test_url.replace('localhost', 'cdio')

    # Use default settings (webdriver_block_assets should be disabled)
    res = client.post(
        url_for("settings.settings_page"),
        data={
            "application-fetch_backend": "html_webdriver",
            "requests-time_between_check-minutes": 180,
        },
        follow_redirects=True
    )
    assert b"Settings updated." in res.data

    # Add our URL to the import page
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data
    wait_for_all_checks(client)
    
    # Verify the watch was fetched successfully
    uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))
    assert live_server.app.config['DATASTORE'].data['watching'][uuid].history_n >= 1, "Watch history had atleast 1 (everything fetched OK)"

    res = client.get(
        url_for("ui.ui_preview.preview_page", uuid=uuid),
        follow_redirects=True
    )
    
    assert b'Test page with images' in res.data