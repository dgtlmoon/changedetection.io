#!/usr/bin/python3
import os
import time
from flask import url_for
from changedetectionio.tests.util import live_server_setup, wait_for_all_checks


# should be proxies.json mounted from run_proxy_tests.sh already
# -v `pwd`/tests/proxy_socks5/proxies.json-example:/app/changedetectionio/test-datastore/proxies.json
def test_socks5_from_proxiesjson_file(client, live_server):
    live_server_setup(live_server)

    test_url = "https://changedetection.io/CHANGELOG.txt?socks-test-tag=" + os.getenv('SOCKSTEST', '')

    res = client.get(url_for("settings_page"))
    assert b'name="requests-proxy" type="radio" value="socks5proxy"' in res.data

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
    assert b'name="proxy" type="radio" value="socks5proxy"' in res.data

    res = client.post(
        url_for("edit_page", uuid="first", unpause_on_save=1),
        data={
            "include_filters": "",
            "fetch_backend": 'html_webdriver' if os.getenv('PLAYWRIGHT_DRIVER_URL') else 'html_requests',
            "headers": "",
            "proxy": "socks5proxy",
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
