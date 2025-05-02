#!/usr/bin/env python3

from flask import url_for
from ..util import live_server_setup, wait_for_all_checks
import os
from ... import strtobool


# Just to be sure the UI outputs the right error message on proxy connection failed
def test_proxy_noconnect_custom(client, live_server, measure_memory_usage):
    live_server_setup(live_server)

    # Goto settings, add our custom one
    res = client.post(
        url_for("settings.settings_page"),
        data={
            "requests-time_between_check-minutes": 180,
            "application-ignore_whitespace": "y",
            "application-fetch_backend": 'html_webdriver' if os.getenv('PLAYWRIGHT_DRIVER_URL') else 'html_requests',
            "requests-extra_proxies-0-proxy_name": "custom-test-proxy",
            # test:awesome is set in tests/proxy_list/squid-passwords.txt
            "requests-extra_proxies-0-proxy_url": "http://THISPROXYDOESNTEXIST:3128",
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
    assert b'Page.goto: net::ERR_PROXY_CONNECTION_FAILED' in res.data

    # Requests
    check_string = b'Proxy connection failed?'

    if os.getenv('PLAYWRIGHT_DRIVER_URL') or strtobool(os.getenv('FAST_PUPPETEER_CHROME_FETCHER', 'False')):
        check_string = b'ERR_PROXY_CONNECTION_FAILED'

    if os.getenv("WEBDRIVER_URL"):
        check_string = b'ERR_PROXY_CONNECTION_FAILED'

    assert check_string in res.data

