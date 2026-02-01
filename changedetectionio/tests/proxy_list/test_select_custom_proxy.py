#!/usr/bin/env python3

import time
from flask import url_for
from ..util import live_server_setup, wait_for_all_checks
import os

# just make a request, we will grep in the docker logs to see it actually got called
def test_select_custom(client, live_server, measure_memory_usage, datastore_path):
   #  live_server_setup(live_server) # Setup on conftest per function

    # Goto settings, add our custom one
    res = client.post(
        url_for("settings.settings_page"),
        data={
            "requests-time_between_check-minutes": 180,
            "application-ignore_whitespace": "y",
            "application-fetch_backend": 'html_webdriver' if os.getenv('PLAYWRIGHT_DRIVER_URL') else 'html_requests',
            "requests-extra_proxies-0-proxy_name": "custom-test-proxy",
            # test:awesome is set in tests/proxy_list/squid-passwords.txt
            "requests-extra_proxies-0-proxy_url": "http://test:awesome@squid-custom:3128",
        },
        follow_redirects=True
    )

    assert b"Settings updated." in res.data


    uuid = client.application.config.get('DATASTORE').add_watch(url='https://changedetection.io/CHANGELOG.txt', extras={'paused': True})
    wait_for_all_checks(client)

    res = client.get(url_for("watchlist.index"))
    assert b'Proxy Authentication Required' not in res.data

    res = client.get(
        url_for("ui.ui_preview.preview_page", uuid=uuid),
        follow_redirects=True
    )
    # We should see something via proxy
    assert b' - 0.' in res.data

    #
    # Now we should see the request in the container logs for "squid-squid-custom" because it will be the only default


def test_custom_proxy_validation(client, live_server, measure_memory_usage, datastore_path):
    #  live_server_setup(live_server) # Setup on conftest per function

    # Goto settings, add our custom one
    res = client.post(
        url_for("settings.settings_page"),
        data={
            "requests-time_between_check-minutes": 180,
            "application-ignore_whitespace": "y",
            "application-fetch_backend": 'html_requests',
            "requests-extra_proxies-0-proxy_name": "custom-test-proxy",
            "requests-extra_proxies-0-proxy_url": "xxxxhtt/333??p://test:awesome@squid-custom:3128",
        },
        follow_redirects=True
    )

    assert b"Settings updated." not in res.data
    assert b'Proxy URLs must start with' in res.data


    res = client.post(
        url_for("settings.settings_page"),
        data={
            "requests-time_between_check-minutes": 180,
            "application-ignore_whitespace": "y",
            "application-fetch_backend": 'html_requests',
            "requests-extra_proxies-0-proxy_name": "custom-test-proxy",
            "requests-extra_proxies-0-proxy_url": "https://",
        },
        follow_redirects=True
    )

    assert b"Settings updated." not in res.data
    assert b"Invalid URL." in res.data
    