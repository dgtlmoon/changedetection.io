#!/usr/bin/python3

import time
from flask import url_for
from ..util import live_server_setup, wait_for_all_checks, extract_UUID_from_client

# Add a site in paused mode, add an invalid filter, we should still have visual selector data ready
def test_visual_selector_content_ready(client, live_server):
    import os
    import json

    assert os.getenv('PLAYWRIGHT_DRIVER_URL'), "Needs PLAYWRIGHT_DRIVER_URL set for this test"
    live_server_setup(live_server)
    time.sleep(1)

    # Add our URL to the import page, because the docker container (playwright/selenium) wont be able to connect to our usual test url
    test_url = "https://changedetection.io/ci-test/test-runjs.html"

    res = client.post(
        url_for("form_quick_watch_add"),
        data={"url": test_url, "tag": '', 'edit_and_watch_submit_button': 'Edit > Watch'},
        follow_redirects=True
    )
    assert b"Watch added in Paused state, saving will unpause" in res.data

    res = client.post(
        url_for("edit_page", uuid="first", unpause_on_save=1),
        data={
              "url": test_url,
              "tag": "",
              "headers": "",
              'fetch_backend': "html_webdriver",
              'webdriver_js_execute_code': 'document.querySelector("button[name=test-button]").click();'
        },
        follow_redirects=True
    )
    assert b"unpaused" in res.data
    time.sleep(1)
    wait_for_all_checks(client)
    uuid = extract_UUID_from_client(client)

    # Check the JS execute code before extract worked
    res = client.get(
        url_for("preview_page", uuid="first"),
        follow_redirects=True
    )
    assert b'I smell JavaScript' in res.data

    assert os.path.isfile(os.path.join('test-datastore', uuid, 'last-screenshot.png')), "last-screenshot.png should exist"
    assert os.path.isfile(os.path.join('test-datastore', uuid, 'elements.json')), "xpath elements.json data should exist"

    # Open it and see if it roughly looks correct
    with open(os.path.join('test-datastore', uuid, 'elements.json'), 'r') as f:
        json.load(f)
