#!/usr/bin/env python3

from flask import url_for
from .util import set_original_response, set_modified_response, live_server_setup, wait_for_all_checks
import time


def set_nonrenderable_response():
    test_return_data = """<html>
    <head><title>modified head title</title></head>
    <!-- like when some angular app was broken and doesnt render or whatever -->
    <body>
     </body>
     </html>
    """
    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)
    time.sleep(1)

    return None

def set_zero_byte_response():
    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write("")
    time.sleep(1)
    return None

def test_check_basic_change_detection_functionality(client, live_server, measure_memory_usage):
    set_original_response()
    live_server_setup(live_server)

    # Add our URL to the import page
    res = client.post(
        url_for("import_page"),
        data={"urls": url_for('test_endpoint', _external=True)},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data

    wait_for_all_checks(client)

    # It should report nothing found (no new 'unviewed' class)
    res = client.get(url_for("index"))
    assert b'unviewed' not in res.data


    #####################
    client.post(
        url_for("settings_page"),
        data={"application-empty_pages_are_a_change": "", # default, OFF, they are NOT a change
              "requests-time_between_check-minutes": 180,
              'application-fetch_backend': "html_requests"},
        follow_redirects=True
    )

    # this should not trigger a change, because no good text could be converted from the HTML
    set_nonrenderable_response()

    client.get(url_for("form_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    wait_for_all_checks(client)

    # It should report nothing found (no new 'unviewed' class)
    res = client.get(url_for("index"))
    assert b'unviewed' not in res.data

    uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))
    watch = live_server.app.config['DATASTORE'].data['watching'][uuid]

    assert watch.last_changed == 0
    assert watch['last_checked'] != 0




    # ok now do the opposite

    client.post(
        url_for("settings_page"),
        data={"application-empty_pages_are_a_change": "y",
              "requests-time_between_check-minutes": 180,
              'application-fetch_backend': "html_requests"},
        follow_redirects=True
    )
    set_modified_response()


    client.get(url_for("form_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    wait_for_all_checks(client)

    # It should report nothing found (no new 'unviewed' class)
    res = client.get(url_for("index"))
    assert b'unviewed' in res.data
    client.get(url_for("mark_all_viewed"), follow_redirects=True)

    # A totally zero byte (#2528) response should also not trigger an error
    set_zero_byte_response()
    client.get(url_for("form_watch_checknow"), follow_redirects=True)

    # 2877
    assert watch.last_changed == watch['last_checked']

    wait_for_all_checks(client)
    res = client.get(url_for("index"))
    assert b'unviewed' in res.data # A change should have registered because empty_pages_are_a_change is ON
    assert b'fetch-error' not in res.data

    #
    # Cleanup everything
    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

