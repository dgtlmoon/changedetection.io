#!/usr/bin/env python3

import os
from flask import url_for
from ..util import live_server_setup, wait_for_all_checks


def test_preferred_proxy(client, live_server, measure_memory_usage, datastore_path):
   #  live_server_setup(live_server) # Setup on conftest per function
    url = "http://chosen.changedetection.io"


    uuid = client.application.config.get('DATASTORE').add_watch(url=url, extras={'paused': True})

    wait_for_all_checks(client)
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid, unpause_on_save=1),
        data={
                "include_filters": "",
                "fetch_backend": 'html_webdriver' if os.getenv('PLAYWRIGHT_DRIVER_URL') else 'html_requests',
                "headers": "",
                "proxy": "proxy-two",
                "tags": "",
                "url": url,
                "time_between_check_use_default": "y",
              },
        follow_redirects=True
    )
    assert b"unpaused" in res.data
    wait_for_all_checks(client)
    # Now the request should appear in the second-squid logs
