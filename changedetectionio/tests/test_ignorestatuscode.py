#!/usr/bin/env python3

import time
from flask import url_for
from .util import live_server_setup, wait_for_all_checks





def set_original_response():
    test_return_data = """<html>
       <body>
     Some initial text<br>
     <p>Which is across multiple lines</p>
     <br>
     So let's see what happens.  <br>
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)


def set_some_changed_response():
    test_return_data = """<html>
       <body>
     Some initial text<br>
     <p>Which is across multiple lines, and a new thing too.</p>
     <br>
     So let's see what happens.  <br>
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)


def test_normal_page_check_works_with_ignore_status_code(client, live_server, measure_memory_usage):


    # Give the endpoint time to spin up
    time.sleep(1)

    set_original_response()

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
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    wait_for_all_checks(client)

    set_some_changed_response()
    wait_for_all_checks(client)
    # Trigger a check
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    wait_for_all_checks(client)

    # It should report nothing found (no new 'unviewed' class)
    res = client.get(url_for("watchlist.index"))
    assert b'unviewed' in res.data
    assert b'/test-endpoint' in res.data


# Tests the whole stack works with staus codes ignored
def test_403_page_check_works_with_ignore_status_code(client, live_server, measure_memory_usage):
    sleep_time_for_fetch_thread = 3

    set_original_response()

    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', status_code=403, _external=True)
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    # Give the thread time to pick it up
    time.sleep(sleep_time_for_fetch_thread)

    # Goto the edit page, check our ignore option
    # Add our URL to the import page
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={"ignore_status_codes": "y", "url": test_url, "tags": "", "headers": "", 'fetch_backend': "html_requests"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    # Give the thread time to pick it up
    wait_for_all_checks(client)

    #  Make a change
    set_some_changed_response()

    # Trigger a check
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    # Give the thread time to pick it up
    wait_for_all_checks(client)

    # It should have 'unviewed' still
    # Because it should be looking at only that 'sametext' id
    res = client.get(url_for("watchlist.index"))
    assert b'unviewed' in res.data

