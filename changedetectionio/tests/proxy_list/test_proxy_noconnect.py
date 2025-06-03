#!/usr/bin/env python3

from flask import url_for
from ..util import live_server_setup, wait_for_all_checks
import os
from ... import strtobool


# Just to be sure the UI outputs the right error message on proxy connection failed
# docker run -p 4444:4444 --rm --shm-size="2g"  selenium/standalone-chrome:4
# PLAYWRIGHT_DRIVER_URL=ws://127.0.0.1:3000 pytest tests/proxy_list/test_proxy_noconnect.py
# FAST_PUPPETEER_CHROME_FETCHER=True PLAYWRIGHT_DRIVER_URL=ws://127.0.0.1:3000 pytest tests/proxy_list/test_proxy_noconnect.py
# WEBDRIVER_URL=http://127.0.0.1:4444/wd/hub pytest tests/proxy_list/test_proxy_noconnect.py

def test_proxy_noconnect_custom(client, live_server, measure_memory_usage):
   #  live_server_setup(live_server) # Setup on conftest per function

    # Goto settings, add our custom one
    res = client.post(
        url_for("settings.settings_page"),
        data={
            "requests-time_between_check-minutes": 180,
            "application-ignore_whitespace": "y",
            "application-fetch_backend": 'html_webdriver' if os.getenv('PLAYWRIGHT_DRIVER_URL') or os.getenv("WEBDRIVER_URL") else 'html_requests',
            "requests-extra_proxies-0-proxy_name": "custom-test-proxy",
            # test:awesome is set in tests/proxy_list/squid-passwords.txt
            "requests-extra_proxies-0-proxy_url": "http://127.0.0.1:3128",
        },
        follow_redirects=True
    )

    assert b"Settings updated." in res.data

    test_url = "https://changedetection.io"
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": '', 'edit_and_watch_submit_button': 'Edit > Watch'},
        follow_redirects=True
    )

    assert b"Watch added in Paused state, saving will unpause" in res.data

    options = {
        "url": test_url,
        "fetch_backend": "html_webdriver" if os.getenv('PLAYWRIGHT_DRIVER_URL') or os.getenv("WEBDRIVER_URL") else "html_requests",
        "proxy": "ui-0custom-test-proxy",
    }

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first", unpause_on_save=1),
        data=options,
        follow_redirects=True
    )
    assert b"unpaused" in res.data
    import time
    wait_for_all_checks(client)

    # Requests default
    check_string = b'Cannot connect to proxy'

    if os.getenv('PLAYWRIGHT_DRIVER_URL') or strtobool(os.getenv('FAST_PUPPETEER_CHROME_FETCHER', 'False')) or os.getenv("WEBDRIVER_URL"):
        check_string = b'ERR_PROXY_CONNECTION_FAILED'


    res = client.get(url_for("watchlist.index"))
    #with open("/tmp/debug.html", 'wb') as f:
    #    f.write(res.data)
    assert check_string in res.data
