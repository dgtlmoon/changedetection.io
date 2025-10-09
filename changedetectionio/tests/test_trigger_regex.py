#!/usr/bin/env python3

import time
from flask import url_for
from .util import live_server_setup, wait_for_all_checks, delete_all_watches


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



def test_trigger_regex_functionality(client, live_server, measure_memory_usage):

   #  live_server_setup(live_server) # Setup on conftest per function

    set_original_ignore_response()

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    wait_for_all_checks(client)

    # It should report nothing found (just a new one shouldnt have anything)
    res = client.get(url_for("watchlist.index"))
    assert b'has-unread-changes' not in res.data

    ### test regex
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={"trigger_text": '/something \d{3}/',
              "url": test_url,
              "fetch_backend": "html_requests",
              "time_between_check_use_default": "y"},
        follow_redirects=True
    )
    wait_for_all_checks(client)
    # so that we set the state to 'has-unread-changes' after all the edits
    client.get(url_for("ui.ui_views.diff_history_page", uuid="first"))

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write("some new noise")

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # It should report nothing found (nothing should match the regex)
    res = client.get(url_for("watchlist.index"))
    assert b'has-unread-changes' not in res.data

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write("regex test123<br>\nsomething 123")

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    res = client.get(url_for("watchlist.index"))
    assert b'has-unread-changes' in res.data

    # Cleanup everything
    delete_all_watches(client)
