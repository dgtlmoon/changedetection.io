#!/usr/bin/python3

import time
from flask import url_for
from .util import live_server_setup


def set_original_ignore_response():
    test_return_data = """<html>
     <body>
     <p>Some initial text</p>
     <p>Which is across multiple lines</p>
     <p>So let's see what happens.</p>
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)


# The same but just re-ordered the text
def set_modified_swapped_lines():
    # Re-ordered and with some whitespacing, should get stripped() too.
    test_return_data = """<html>
     <body>
     <p>Some initial text</p>
     <p>   So let's see what happens.</p>
     <p>&nbsp;Which is across multiple lines</p>     
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)


def set_modified_with_trigger_text_response():
    test_return_data = """<html>
     <body>
     <p>Some initial text</p>
     <p>So let's see what happens.</p>
     <p>and a new line!</p>
     <p>Which is across multiple lines</p>     
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)


def test_unique_lines_functionality(client, live_server):
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
    time.sleep(sleep_time_for_fetch_thread)

    # Add our URL to the import page
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"check_unique_lines": "y",
              "url": test_url,
              "fetch_backend": "html_requests"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    assert b'unviewed' not in res.data

    #  Make a change
    set_modified_swapped_lines()

    time.sleep(sleep_time_for_fetch_thread)
    # Trigger a check
    client.get(url_for("form_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(sleep_time_for_fetch_thread)

    # It should report nothing found (no new 'unviewed' class)
    res = client.get(url_for("index"))
    assert b'unviewed' not in res.data


    # Now set the content which contains the new text and re-ordered existing text
    set_modified_with_trigger_text_response()
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    time.sleep(sleep_time_for_fetch_thread)
    res = client.get(url_for("index"))
    assert b'unviewed' in res.data

