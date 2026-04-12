#!/usr/bin/env python3

import time
from flask import url_for
from .util import live_server_setup, wait_for_all_checks
import os





def set_original_response(datastore_path):
    test_return_data = """<html>
       <body>
     Some initial text<br>
     <p>Which is across multiple lines</p>
     <br>
     So let's see what happens.  <br>
     </body>
     </html>
    """

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)


def set_some_changed_response(datastore_path):
    test_return_data = """<html>
       <body>
     Some initial text<br>
     <p>Which is across multiple lines, and a new thing too.</p>
     <br>
     So let's see what happens.  <br>
     </body>
     </html>
    """

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)


def test_normal_page_check_works_with_ignore_status_code(client, live_server, measure_memory_usage, datastore_path):
    from loguru import logger

    set_original_response(datastore_path=datastore_path)

    # Goto the settings page, add our ignore text
    res = client.post(
        url_for("settings.settings_page"),
        data={
            "requests-time_between_check-minutes": 180,
            "application-ignore_status_codes": "y",
            'application-fetch_backend': "html_requests"
        },
        follow_redirects=True
    )
    assert b"Settings updated." in res.data

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)

    logger.info(f"TEST: First check - queuing UUID {uuid}")
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    logger.info(f"TEST: Waiting for first check to complete")
    wait_result = wait_for_all_checks(client)
    logger.info(f"TEST: First check wait completed: {wait_result}")

    # Check history after first check
    watch = client.application.config.get('DATASTORE').data['watching'][uuid]
    logger.info(f"TEST: After first check - history count: {len(watch.history.keys())}")

    set_some_changed_response(datastore_path=datastore_path)

    # Trigger a check
    logger.info(f"TEST: Second check - queuing UUID {uuid}")
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    logger.info(f"TEST: Waiting for second check to complete")
    wait_result = wait_for_all_checks(client)
    logger.info(f"TEST: Second check wait completed: {wait_result}")

    # Check history after second check
    watch = client.application.config.get('DATASTORE').data['watching'][uuid]
    logger.info(f"TEST: After second check - history count: {len(watch.history.keys())}")
    logger.info(f"TEST: Watch history keys: {list(watch.history.keys())}")

    # It should report nothing found (no new 'has-unread-changes' class)
    res = client.get(url_for("watchlist.index"))

    if b'has-unread-changes' not in res.data:
        logger.error(f"TEST FAILED: has-unread-changes not found in response")
        logger.error(f"TEST: Watch last_error: {watch.get('last_error')}")
        logger.error(f"TEST: Watch last_checked: {watch.get('last_checked')}")

    assert b'has-unread-changes' in res.data
    assert b'/test-endpoint' in res.data


# Tests the whole stack works with staus codes ignored
def test_403_page_check_works_with_ignore_status_code(client, live_server, measure_memory_usage, datastore_path):

    set_original_response(datastore_path=datastore_path)

    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', status_code=403, _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    wait_for_all_checks(client)

    # Goto the edit page, check our ignore option
    # Add our URL to the import page
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={"ignore_status_codes": "y", "url": test_url, "tags": "", "headers": "", 'fetch_backend': "html_requests", "time_between_check_use_default": "y"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    # Give the thread time to pick it up
    wait_for_all_checks(client)

    #  Make a change
    set_some_changed_response(datastore_path=datastore_path)

    # Trigger a check
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    # Give the thread time to pick it up
    wait_for_all_checks(client)

    # It should have 'has-unread-changes' still
    # Because it should be looking at only that 'sametext' id
    res = client.get(url_for("watchlist.index"))
    assert b'has-unread-changes' in res.data

