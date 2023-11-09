#!/usr/bin/python3

import time
import os
from flask import url_for
from ..util import live_server_setup, wait_for_all_checks, extract_UUID_from_client

def test_setup(client, live_server):
    live_server_setup(live_server)

# Add a site in paused mode, add an invalid filter, we should still have visual selector data ready
def test_visual_selector_content_ready(client, live_server):
    import os
    import json

    assert os.getenv('PLAYWRIGHT_DRIVER_URL'), "Needs PLAYWRIGHT_DRIVER_URL set for this test"

    # Add our URL to the import page, because the docker container (playwright/selenium) wont be able to connect to our usual test url
    test_url = "https://changedetection.io/ci-test/test-runjs.html"

    res = client.post(
        url_for("form_quick_watch_add"),
        data={"url": test_url, "tags": '', 'edit_and_watch_submit_button': 'Edit > Watch'},
        follow_redirects=True
    )
    assert b"Watch added in Paused state, saving will unpause" in res.data

    res = client.post(
        url_for("edit_page", uuid="first", unpause_on_save=1),
        data={
              "url": test_url,
              "tags": "",
              "headers": "",
              'fetch_backend': "html_webdriver",
              'webdriver_js_execute_code': 'document.querySelector("button[name=test-button]").click();'
        },
        follow_redirects=True
    )
    assert b"unpaused" in res.data
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

    # Attempt to fetch it via the web hook that the browser would use
    res = client.get(url_for('static_content', group='visual_selector_data', filename=uuid))
    json.loads(res.data)
    assert res.mimetype == 'application/json'
    assert res.status_code == 200


    # Some options should be enabled
    # @todo - in the future, the visibility should be toggled by JS from the request type setting
    res = client.get(
        url_for("edit_page", uuid="first"),
        follow_redirects=True
    )
    assert b'notification_screenshot' in res.data
    client.get(
        url_for("form_delete", uuid="all"),
        follow_redirects=True
    )

def test_basic_browserstep(client, live_server):

    assert os.getenv('PLAYWRIGHT_DRIVER_URL'), "Needs PLAYWRIGHT_DRIVER_URL set for this test"
    #live_server_setup(live_server)

    # Add our URL to the import page, because the docker container (playwright/selenium) wont be able to connect to our usual test url
    test_url = "https://changedetection.io/ci-test/test-runjs.html"

    res = client.post(
        url_for("form_quick_watch_add"),
        data={"url": test_url, "tags": '', 'edit_and_watch_submit_button': 'Edit > Watch'},
        follow_redirects=True
    )
    assert b"Watch added in Paused state, saving will unpause" in res.data

    res = client.post(
        url_for("edit_page", uuid="first", unpause_on_save=1),
        data={
              "url": test_url,
              "tags": "",
              "headers": "",
              'fetch_backend': "html_webdriver",
              'browser_steps-0-operation': 'Goto site',
              'browser_steps-1-operation': 'Click element',
              'browser_steps-1-selector': 'button[name=test-button]',
              'browser_steps-1-optional_value': ''
        },
        follow_redirects=True
    )
    assert b"unpaused" in res.data
    wait_for_all_checks(client)

    uuid = extract_UUID_from_client(client)

    # Check HTML conversion detected and workd
    res = client.get(
        url_for("preview_page", uuid=uuid),
        follow_redirects=True
    )
    assert b"This text should be removed" not in res.data
    assert b"I smell JavaScript because the button was pressed" in res.data

    # now test for 404 errors
    res = client.post(
        url_for("edit_page", uuid=uuid, unpause_on_save=1),
        data={
              "url": "https://changedetection.io/404",
              "tags": "",
              "headers": "",
              'fetch_backend': "html_webdriver",
              'browser_steps-0-operation': 'Goto site',
              'browser_steps-1-operation': 'Click element',
              'browser_steps-1-selector': 'button[name=test-button]',
              'browser_steps-1-optional_value': ''
        },
        follow_redirects=True
    )
    assert b"unpaused" in res.data
    wait_for_all_checks(client)

    res = client.get(url_for("index"))
    assert b'Error - 404' in res.data

    client.get(
        url_for("form_delete", uuid="all"),
        follow_redirects=True
    )