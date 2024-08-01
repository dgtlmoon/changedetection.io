#!/usr/bin/env python3

import time
from flask import url_for
from ..util import live_server_setup, wait_for_all_checks, extract_UUID_from_client


def test_noproxy_option(client, live_server, measure_memory_usage):
    live_server_setup(live_server)
    # Run by run_proxy_tests.sh
    # Call this URL then scan the containers that it never went through them
    url = "http://noproxy.changedetection.io"

    # Should only be available when a proxy is setup
    res = client.get(
        url_for("edit_page", uuid="first", unpause_on_save=1))
    assert b'No proxy' not in res.data

    # Setup a proxy
    res = client.post(
        url_for("settings_page"),
        data={
            "requests-time_between_check-minutes": 180,
            "application-ignore_whitespace": "y",
            "application-fetch_backend": "html_requests",
            "requests-extra_proxies-0-proxy_name": "custom-one-proxy",
            "requests-extra_proxies-0-proxy_url": "http://test:awesome@squid-one:3128",
            "requests-extra_proxies-1-proxy_name": "custom-two-proxy",
            "requests-extra_proxies-1-proxy_url": "http://test:awesome@squid-two:3128",
            "requests-extra_proxies-2-proxy_name": "custom-proxy",
            "requests-extra_proxies-2-proxy_url": "http://test:awesome@squid-custom:3128",
        },
        follow_redirects=True
    )

    assert b"Settings updated." in res.data

    # Should be available as an option
    res = client.get(
        url_for("settings_page", unpause_on_save=1))
    assert b'No proxy' in res.data


    # This will add it paused
    res = client.post(
        url_for("form_quick_watch_add"),
        data={"url": url, "tags": '', 'edit_and_watch_submit_button': 'Edit > Watch'},
        follow_redirects=True
    )
    assert b"Watch added in Paused state, saving will unpause" in res.data
    uuid = extract_UUID_from_client(client)
    res = client.get(
        url_for("edit_page", uuid=uuid, unpause_on_save=1))
    assert b'No proxy' in res.data

    res = client.post(
        url_for("edit_page", uuid=uuid, unpause_on_save=1),
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
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    # Now the request should NOT appear in the second-squid logs (handled by the run_test_proxies.sh script)

    # Prove that it actually checked

    assert live_server.app.config['DATASTORE'].data['watching'][uuid]['last_checked'] != 0

