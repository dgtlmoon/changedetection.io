#!/usr/bin/env python3

import time
from flask import url_for

from .util import live_server_setup, delete_all_watches, wait_for_all_checks
import os


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



def test_trigger_regex_functionality_with_filter(client, live_server, measure_memory_usage, datastore_path):

    set_original_ignore_response(datastore_path=datastore_path)

    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    wait_for_all_checks(client)

    ### test regex with filter
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={"trigger_text": "/cool.stuff/",
              "url": test_url,
              "include_filters": '#in-here',
              "fetch_backend": "html_requests",
              "time_between_check_use_default": "y"},
        follow_redirects=True
    )

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    wait_for_all_checks(client)

    client.get(url_for("ui.ui_diff.diff_history_page", uuid="first"))

    # Check that we have the expected text.. but it's not in the css filter we want
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write("<html>some new noise with cool stuff2 ok</html>")

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    wait_for_all_checks(client)

    # It should report nothing found (nothing should match the regex and filter)
    res = client.get(url_for("watchlist.index"))
    assert b'has-unread-changes' not in res.data

    # now this should trigger something
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write("<html>some new noise with <span id=in-here>cool stuff6</span> ok</html>")

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    wait_for_all_checks(client)
    res = client.get(url_for("watchlist.index"))
    assert b'has-unread-changes' in res.data

# Cleanup everything
    delete_all_watches(client)
