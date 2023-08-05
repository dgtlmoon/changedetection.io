#!/usr/bin/python3

import time
from flask import url_for
from urllib.request import urlopen
from .util import set_original_response, set_modified_response, live_server_setup

sleep_time_for_fetch_thread = 3


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

    return None

def test_check_basic_change_detection_functionality(client, live_server):
    set_original_response()
    live_server_setup(live_server)

    # Add our URL to the import page
    res = client.post(
        url_for("import_page"),
        data={"urls": url_for('test_endpoint', _external=True)},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data

    time.sleep(sleep_time_for_fetch_thread)

    # Do this a few times.. ensures we dont accidently set the status
    for n in range(3):
        client.get(url_for("form_watch_checknow"), follow_redirects=True)

        # Give the thread time to pick it up
        time.sleep(sleep_time_for_fetch_thread)

        # It should report nothing found (no new 'unviewed' class)
        res = client.get(url_for("index"))
        assert b'unviewed' not in res.data


    #####################
    client.post(
        url_for("settings_page"),
        data={"application-empty_pages_are_a_change": "",
              "requests-time_between_check-minutes": 180,
              'application-fetch_backend': "html_requests"},
        follow_redirects=True
    )

    # this should not trigger a change, because no good text could be converted from the HTML
    set_nonrenderable_response()

    client.get(url_for("form_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(sleep_time_for_fetch_thread)

    # It should report nothing found (no new 'unviewed' class)
    res = client.get(url_for("index"))
    assert b'unviewed' not in res.data


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
    time.sleep(sleep_time_for_fetch_thread)

    # It should report nothing found (no new 'unviewed' class)
    res = client.get(url_for("index"))
    assert b'unviewed' in res.data




    #
    # Cleanup everything
    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

