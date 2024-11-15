#!/usr/bin/env python3
import os

from flask import url_for
from ..util import live_server_setup, wait_for_all_checks

def do_test(client, live_server, make_test_use_extra_browser=False):

    # Grep for this string in the logs?
    test_url = f"https://changedetection.io/ci-test.html?non-custom-default=true"
    # "non-custom-default" should not appear in the custom browser connection
    custom_browser_name = 'custom browser URL'

    # needs to be set and something like 'ws://127.0.0.1:3000'
    assert os.getenv('PLAYWRIGHT_DRIVER_URL'), "Needs PLAYWRIGHT_DRIVER_URL set for this test"

    #####################
    res = client.post(
        url_for("settings_page"),
        data={"application-empty_pages_are_a_change": "",
              "requests-time_between_check-minutes": 180,
              'application-fetch_backend': "html_webdriver",
              'requests-extra_browsers-0-browser_connection_url': 'ws://sockpuppetbrowser-custom-url:3000',
              'requests-extra_browsers-0-browser_name': custom_browser_name
              },
        follow_redirects=True
    )

    assert b"Settings updated." in res.data

    # Add our URL to the import page
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data
    wait_for_all_checks(client)

    if make_test_use_extra_browser:

        # So the name should appear in the edit page under "Request" > "Fetch Method"
        res = client.get(
            url_for("edit_page", uuid="first"),
            follow_redirects=True
        )
        assert b'custom browser URL' in res.data

        res = client.post(
            url_for("edit_page", uuid="first"),
            data={
                # 'run_customer_browser_url_tests.sh' will search for this string to know if we hit the right browser container or not
                  "url": f"https://changedetection.io/ci-test.html?custom-browser-search-string=1",
                  "tags": "",
                  "headers": "",
                  'fetch_backend': f"extra_browser_{custom_browser_name}",
                  'webdriver_js_execute_code': ''
            },
            follow_redirects=True
        )

        assert b"Updated watch." in res.data
        wait_for_all_checks(client)

    # Force recheck
    res = client.get(url_for("form_watch_checknow"), follow_redirects=True)
    assert b'1 watches queued for rechecking.' in res.data

    wait_for_all_checks(client)

    res = client.get(
        url_for("preview_page", uuid="first"),
        follow_redirects=True
    )
    assert b'cool it works' in res.data


# Requires playwright to be installed
def test_request_via_custom_browser_url(client, live_server, measure_memory_usage):
    live_server_setup(live_server)
    # We do this so we can grep the logs of the custom container and see if the request actually went through that container
    do_test(client, live_server, make_test_use_extra_browser=True)


def test_request_not_via_custom_browser_url(client, live_server, measure_memory_usage):
    live_server_setup(live_server)
    # We do this so we can grep the logs of the custom container and see if the request actually went through that container
    do_test(client, live_server, make_test_use_extra_browser=False)
