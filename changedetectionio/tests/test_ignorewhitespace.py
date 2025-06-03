#!/usr/bin/env python3

import time
from flask import url_for
from . util import live_server_setup




# Should be the same as set_original_ignore_response() but with a little more whitespacing
def set_original_ignore_response_but_with_whitespace():
    test_return_data = """<html>
       <body>
     Some initial text<br>
     <p>


     Which is across multiple lines</p>
     <br>
     <br>

         So let's see what happens.  <br>


     </body>
     </html>

    """
    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)


def set_original_ignore_response():
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



# If there was only a change in the whitespacing, then we shouldnt have a change detected
def test_check_ignore_whitespace(client, live_server, measure_memory_usage):
    sleep_time_for_fetch_thread = 3

    # Give the endpoint time to spin up
    time.sleep(1)

    set_original_ignore_response()

    # Goto the settings page, add our ignore text
    res = client.post(
        url_for("settings.settings_page"),
        data={
            "requests-time_between_check-minutes": 180,
            "application-ignore_whitespace": "y",
            "application-fetch_backend": "html_requests"
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

    time.sleep(sleep_time_for_fetch_thread)
    # Trigger a check
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    set_original_ignore_response_but_with_whitespace()
    time.sleep(sleep_time_for_fetch_thread)
    # Trigger a check
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(sleep_time_for_fetch_thread)

    # It should report nothing found (no new 'unviewed' class)
    res = client.get(url_for("watchlist.index"))
    assert b'unviewed' not in res.data
    assert b'/test-endpoint' in res.data
