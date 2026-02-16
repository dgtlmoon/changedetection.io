#!/usr/bin/env python3

import time
from flask import url_for
import os

from .util import live_server_setup, delete_all_watches, wait_for_all_checks


# Should be the same as set_original_ignore_response(datastore_path=datastore_path) but with a little more whitespacing
def set_original_ignore_response_but_with_whitespace(datastore_path):
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
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)


def set_original_ignore_response(datastore_path):
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



# If there was only a change in the whitespacing, then we shouldnt have a change detected
def test_check_ignore_whitespace(client, live_server, measure_memory_usage, datastore_path):


    set_original_ignore_response(datastore_path=datastore_path)

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
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    wait_for_all_checks(client)
    # Trigger a check
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    set_original_ignore_response_but_with_whitespace(datastore_path)
    wait_for_all_checks(client)
    # Trigger a check
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    wait_for_all_checks(client)

    # It should report nothing found (no new 'has-unread-changes' class)
    res = client.get(url_for("watchlist.index"))
    assert b'has-unread-changes' not in res.data
    assert b'/test-endpoint' in res.data
