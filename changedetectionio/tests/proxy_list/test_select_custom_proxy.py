#!/usr/bin/env python3

import time
from flask import url_for
from ..util import live_server_setup, wait_for_all_checks
import os

# just make a request, we will grep in the docker logs to see it actually got called
def test_select_custom(client, live_server, measure_memory_usage):
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

    res = client.post(
        url_for("imports.import_page"),
        # Because a URL wont show in squid/proxy logs due it being SSLed
        # Use plain HTTP or a specific domain-name here
        data={"urls": "https://changedetection.io/CHANGELOG.txt"},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data
    wait_for_all_checks(client)

    res = client.get(url_for("watchlist.index"))
    assert b'Proxy Authentication Required' not in res.data

    res = client.get(
        url_for("ui.ui_views.preview_page", uuid="first"),
        follow_redirects=True
    )
    # We should see something via proxy
    assert b' - 0.' in res.data

    #
    # Now we should see the request in the container logs for "squid-squid-custom" because it will be the only default

