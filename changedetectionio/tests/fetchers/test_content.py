#!/usr/bin/env python3

import time
from flask import url_for
from ..util import live_server_setup, wait_for_all_checks
import logging

# Requires playwright to be installed
def test_fetch_webdriver_content(client, live_server, measure_memory_usage):
   #  live_server_setup(live_server) # Setup on conftest per function

    #####################
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-empty_pages_are_a_change": "",
              "requests-time_between_check-minutes": 180,
              'application-fetch_backend': "html_webdriver"},
        follow_redirects=True
    )

    assert b"Settings updated." in res.data

    # Add our URL to the import page
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": "https://changedetection.io/ci-test.html"},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data
    wait_for_all_checks(client)


    res = client.get(
        url_for("ui.ui_views.preview_page", uuid="first"),
        follow_redirects=True
    )
    logging.getLogger().info("Looking for correct fetched HTML (text) from server")

    assert b'cool it works' in res.data
