#!/usr/bin/python3

import time
from flask import url_for
from ..util import live_server_setup
import logging


def test_fetch_webdriver_content(client, live_server):
    live_server_setup(live_server)

    #####################
    res = client.post(
        url_for("settings_page"),
        data={"application-empty_pages_are_a_change": "",
              "requests-time_between_check-minutes": 180,
              'application-fetch_backend': "html_webdriver"},
        follow_redirects=True
    )

    assert b"Settings updated." in res.data

    # Add our URL to the import page
    res = client.post(
        url_for("import_page"),
        data={"urls": "https://changedetection.io/ci-test.html"},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data
    time.sleep(3)
    attempt = 0
    while attempt < 20:
        res = client.get(url_for("index"))
        if not b'Checking now' in res.data:
            break
        logging.getLogger().warning("Waiting for WebDriver to complete..")
        time.sleep(3)
        attempt += 1


    res = client.get(
        url_for("preview_page", uuid="first"),
        follow_redirects=True
    )
    with open('/tmp/fuck.html', 'wb') as f:
        f.write(res.data)

    assert b'cool it works' in res.data