#!/usr/bin/python3

import time
from flask import url_for
from ..util import live_server_setup, wait_for_all_checks, extract_UUID_from_client

def test_check_basic_change_detection_functionality(client, live_server):
    time.sleep(1)
    live_server_setup(live_server)
    time.sleep(1)
    res = client.post(
        url_for("import_page"),
        # Because a URL wont show in squid/proxy logs due it being SSLed
        # Use plain HTTP or a specific domain-name here
        data={"urls": "http://one.changedetection.io"},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data
    time.sleep(2)
