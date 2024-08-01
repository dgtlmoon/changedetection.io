#!/usr/bin/env python3

import time
from flask import url_for
from . util import live_server_setup


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



def test_trigger_regex_functionality_with_filter(client, live_server, measure_memory_usage):

    live_server_setup(live_server)
    sleep_time_for_fetch_thread = 3

    set_original_ignore_response()

    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    # it needs time to save the original version
    time.sleep(sleep_time_for_fetch_thread)

    ### test regex with filter
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"trigger_text": "/cool.stuff/",
              "url": test_url,
              "include_filters": '#in-here',
              "fetch_backend": "html_requests"},
        follow_redirects=True
    )

    # Give the thread time to pick it up
    time.sleep(sleep_time_for_fetch_thread)

    client.get(url_for("diff_history_page", uuid="first"))

    # Check that we have the expected text.. but it's not in the css filter we want
    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write("<html>some new noise with cool stuff2 ok</html>")

    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    time.sleep(sleep_time_for_fetch_thread)

    # It should report nothing found (nothing should match the regex and filter)
    res = client.get(url_for("index"))
    assert b'unviewed' not in res.data

    # now this should trigger something
    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write("<html>some new noise with <span id=in-here>cool stuff6</span> ok</html>")

    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    time.sleep(sleep_time_for_fetch_thread)
    res = client.get(url_for("index"))
    assert b'unviewed' in res.data

# Cleanup everything
    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data
