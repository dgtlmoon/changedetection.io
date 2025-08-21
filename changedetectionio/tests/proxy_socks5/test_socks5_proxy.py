#!/usr/bin/env python3
import json
import os
from flask import url_for
from changedetectionio.tests.util import live_server_setup, wait_for_all_checks, extract_UUID_from_client


def set_response():
    import time
    data = """<html>
       <body>
     <h1>Awesome, you made it</h1>
     yeah the socks request worked
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(data)
    time.sleep(1)

def test_socks5(client, live_server, measure_memory_usage):
   #  live_server_setup(live_server) # Setup on conftest per function
    set_response()

    # Setup a proxy
    res = client.post(
        url_for("settings.settings_page"),
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

    # Because the socks server should connect back to us
    test_url = url_for('test_endpoint', _external=True) + f"?socks-test-tag={os.getenv('SOCKSTEST', '')}"
    test_url = test_url.replace('localhost.localdomain', 'cdio')
    test_url = test_url.replace('localhost', 'cdio')

    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": '', 'edit_and_watch_submit_button': 'Edit > Watch'},
        follow_redirects=True
    )
    assert b"Watch added in Paused state, saving will unpause" in res.data

    res = client.get(
        url_for("ui.ui_edit.edit_page", uuid="first", unpause_on_save=1),
    )
    # check the proxy is offered as expected
    assert b'ui-0socks5proxy' in res.data

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first", unpause_on_save=1),
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
        url_for("ui.ui_views.preview_page", uuid="first"),
        follow_redirects=True
    )

    # Should see the proper string
    assert "Awesome, you made it".encode('utf-8') in res.data

    # PROXY CHECKER WIDGET CHECK - this needs more checking
    uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))

    res = client.get(
        url_for("check_proxies.start_check", uuid=uuid),
        follow_redirects=True
    )
    # It's probably already finished super fast :(
    #assert b"RUNNING" in res.data
    
    wait_for_all_checks(client)
    res = client.get(
        url_for("check_proxies.get_recheck_status", uuid=uuid),
        follow_redirects=True
    )
    assert b"OK" in res.data

    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

