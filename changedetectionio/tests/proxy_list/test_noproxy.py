#!/usr/bin/python3

import time
from flask import url_for
from ..util import live_server_setup, wait_for_all_checks


def test_preferred_proxy(client, live_server):
    live_server_setup(live_server)
    # Run by run_proxy_tests.sh
    # Call this URL then scan the containers that it never went through them
    url = "http://noproxy.changedetection.io"

    # This will add it paused
    res = client.post(
        url_for("form_quick_watch_add"),
        data={"url": url, "tags": '', 'edit_and_watch_submit_button': 'Edit > Watch'},
        follow_redirects=True
    )
    assert b"Watch added in Paused state, saving will unpause" in res.data

    res = client.post(
        url_for("edit_page", uuid="first", unpause_on_save=1),
        data={
                "include_filters": "",
                "fetch_backend": "html_requests",
                "headers": "",
                "proxy": "no-proxy",
                "tags": "",
                "url": url,
              },
        follow_redirects=True
    )
    assert b"unpaused" in res.data
    wait_for_all_checks(client)
    # Now the request should appear in the second-squid logs
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)