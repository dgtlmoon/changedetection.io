#!/usr/bin/env python3

import time
from flask import url_for
from .util import live_server_setup, wait_for_all_checks


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


def set_modified_original_ignore_response():
    test_return_data = """<html>
       <body>
     Some NEW nice initial text<br>
     <p>Which is across multiple lines</p>
     <br>
     So let's see what happens.  <br>
     </body>
     </html>

    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)


def set_modified_with_trigger_text_response():
    test_return_data = """<html>
       <body>
     Some NEW nice initial text<br>
     <p>Which is across multiple lines</p>
     <br>
     Add to cart
     <br>
     So let's see what happens.  <br>
     </body>
     </html>

    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)


def test_trigger_functionality(client, live_server, measure_memory_usage):

    live_server_setup(live_server)

    trigger_text = "Add to cart"
    set_original_ignore_response()


    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    # Trigger a check
    client.get(url_for("form_watch_checknow"), follow_redirects=True)

    # Goto the edit page, add our ignore text
    # Add our URL to the import page
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"trigger_text": trigger_text,
              "url": test_url,
              "fetch_backend": "html_requests"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    wait_for_all_checks(client)
    # Check it saved
    res = client.get(
        url_for("edit_page", uuid="first"),
    )
    assert bytes(trigger_text.encode('utf-8')) in res.data


    
    # so that we set the state to 'unviewed' after all the edits
    client.get(url_for("diff_history_page", uuid="first"))

    # Trigger a check
    client.get(url_for("form_watch_checknow"), follow_redirects=True)

    wait_for_all_checks(client)

    # It should report nothing found (no new 'unviewed' class)
    res = client.get(url_for("index"))
    assert b'unviewed' not in res.data
    assert b'/test-endpoint' in res.data

    #  Make a change
    set_modified_original_ignore_response()

    # Trigger a check
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # It should report nothing found (no new 'unviewed' class)
    res = client.get(url_for("index"))
    assert b'unviewed' not in res.data

    # Now set the content which contains the trigger text
    set_modified_with_trigger_text_response()

    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    res = client.get(url_for("index"))
    assert b'unviewed' in res.data
    
    # https://github.com/dgtlmoon/changedetection.io/issues/616
    # Apparently the actual snapshot that contains the trigger never shows
    res = client.get(url_for("diff_history_page", uuid="first"))
    assert b'Add to cart' in res.data

    # Check the preview/highlighter, we should be able to see what we triggered on, but it should be highlighted
    res = client.get(url_for("preview_page", uuid="first"))

    # We should be able to see what we triggered on
    # The JS highlighter should tell us which lines (also used in the live-preview)
    assert b'const triggered_line_numbers = [6]' in res.data
    assert b'Add to cart' in res.data

