#!/usr/bin/python3
import os
import time
from flask import url_for
from changedetectionio.tests.util import live_server_setup, wait_for_all_checks


def test_socks5(client, live_server):
    live_server_setup(live_server)

    # Setup a proxy
    res = client.post(
        url_for("settings_page"),
        data={
            "requests-time_between_check-minutes": 180,
            "application-ignore_whitespace": "y",
            "application-fetch_backend": "html_requests",
            # set in .github/workflows/test-only.yml
            "requests-extra_proxies-0-proxy_url": "socks5://proxy_user123:proxy_pass123@socks5proxy:1080",
            "requests-extra_proxies-0-proxy_name": "socks5proxy",
        },
        follow_redirects=True
    )

    assert b"Settings updated." in res.data

    test_url = "https://changedetection.io/CHANGELOG.txt?socks-test-tag=" + os.getenv('SOCKSTEST', '')

    res = client.post(
        url_for("form_quick_watch_add"),
        data={"url": test_url, "tags": '', 'edit_and_watch_submit_button': 'Edit > Watch'},
        follow_redirects=True
    )
    assert b"Watch added in Paused state, saving will unpause" in res.data

    res = client.get(
        url_for("edit_page", uuid="first", unpause_on_save=1),
    )
    # check the proxy is offered as expected
    assert b'ui-0socks5proxy' in res.data

    res = client.post(
        url_for("edit_page", uuid="first", unpause_on_save=1),
        data={
            "include_filters": "",
            "fetch_backend": 'html_webdriver' if os.getenv('PLAYWRIGHT_DRIVER_URL') else 'html_requests',
            "headers": "",
            "proxy": "ui-0socks5proxy",
            "tags": "",
            "url": test_url,
        },
        follow_redirects=True
    )
    assert b"unpaused" in res.data
    wait_for_all_checks(client)

    res = client.get(
        url_for("preview_page", uuid="first"),
        follow_redirects=True
    )

    # Should see the proper string
    assert "+0200:".encode('utf-8') in res.data
