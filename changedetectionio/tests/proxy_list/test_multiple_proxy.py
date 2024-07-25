#!/usr/bin/env python3

import os
from flask import url_for
from ..util import live_server_setup, wait_for_all_checks


def test_preferred_proxy(client, live_server, measure_memory_usage):
    live_server_setup(live_server)
    url = "http://chosen.changedetection.io"


    res = client.post(
        url_for("form_quick_watch_add"),
        data={"url": url, "tags": '', 'edit_and_watch_submit_button': 'Edit > Watch'},
        follow_redirects=True
    )
    assert b"Watch added in Paused state, saving will unpause" in res.data

    wait_for_all_checks(client)
    res = client.post(
        url_for("edit_page", uuid="first", unpause_on_save=1),
        data={
                "include_filters": "",
                "fetch_backend": 'html_webdriver' if os.getenv('PLAYWRIGHT_DRIVER_URL') else 'html_requests',
                "headers": "",
                "proxy": "proxy-two",
                "tags": "",
                "url": url,
              },
        follow_redirects=True
    )
    assert b"unpaused" in res.data
    wait_for_all_checks(client)
    # Now the request should appear in the second-squid logs
