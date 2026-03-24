#!/usr/bin/env python3
import os

from flask import url_for
from ..util import live_server_setup, wait_for_all_checks

CUSTOM_PROFILE_NAME = 'Custom Browser URL'
CUSTOM_PROFILE_MACHINE_NAME = 'custom_browser_url'
CUSTOM_BROWSER_WS = 'ws://sockpuppetbrowser-custom-url:3000'


def create_custom_browser_profile(client):
    """Create a browser profile that uses the custom sockpuppet container."""
    res = client.post(
        url_for("settings_browsers.save"),
        data={
            "name": CUSTOM_PROFILE_NAME,
            "fetch_backend": "webdriver",
            "browser_connection_url": CUSTOM_BROWSER_WS,
            "viewport_width": 1280,
            "viewport_height": 1000,
            "block_images": "",
            "block_fonts": "",
            "ignore_https_errors": "",
            "user_agent": "",
            "locale": "",
            "original_machine_name": "",
        },
        follow_redirects=True
    )
    assert b"saved." in res.data, f"Expected profile save confirmation, got: {res.data[:500]}"


def do_test(client, live_server, make_test_use_extra_browser=False):

    # needs to be set and something like 'ws://127.0.0.1:3000'
    assert os.getenv('PLAYWRIGHT_DRIVER_URL'), "Needs PLAYWRIGHT_DRIVER_URL set for this test"

    test_url = "https://changedetection.io/ci-test.html?non-custom-default=true"

    # Set global default to webdriver (browser-based)
    res = client.post(
        url_for("settings.settings_page"),
        data={
            "application-empty_pages_are_a_change": "",
            "requests-time_between_check-minutes": 180,
            "application-browser_profile": "browser_chromeplaywright",
        },
        follow_redirects=True
    )
    assert b"Settings updated." in res.data

    # Create the custom browser profile
    create_custom_browser_profile(client)

    # Add our URL to the import page
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    if make_test_use_extra_browser:

        # The custom profile name should appear in the edit page under "Request" tab
        res = client.get(
            url_for("ui.ui_edit.edit_page", uuid="first"),
            follow_redirects=True
        )
        assert CUSTOM_PROFILE_NAME.encode() in res.data, \
            f"Expected '{CUSTOM_PROFILE_NAME}' in edit page fetch method choices"

        res = client.post(
            url_for("ui.ui_edit.edit_page", uuid="first"),
            data={
                # 'run_custom_browser_url_tests.sh' will grep for this string in the custom container logs
                "url": "https://changedetection.io/ci-test.html?custom-browser-search-string=1",
                "tags": "",
                "headers": "",
                "browser_profile": CUSTOM_PROFILE_MACHINE_NAME,
                "webdriver_js_execute_code": "",
                "time_between_check_use_default": "y"
            },
            follow_redirects=True
        )

        assert b"Updated watch." in res.data
        wait_for_all_checks(client)

    # Force recheck
    res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    assert b'Queued 1 watch for rechecking.' in res.data

    wait_for_all_checks(client)

    res = client.get(
        url_for("ui.ui_preview.preview_page", uuid="first"),
        follow_redirects=True
    )
    assert b'cool it works' in res.data


# Requires playwright to be installed
def test_request_via_custom_browser_url(client, live_server, measure_memory_usage, datastore_path):
    # We do this so we can grep the logs of the custom container and see if the request actually went through that container
    do_test(client, live_server, make_test_use_extra_browser=True)


def test_request_not_via_custom_browser_url(client, live_server, measure_memory_usage, datastore_path):
    # We do this so we can grep the logs of the custom container and see if the request actually went through that container
    do_test(client, live_server, make_test_use_extra_browser=False)
