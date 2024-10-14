#!/usr/bin/env python3

import time
from flask import url_for
from .util import live_server_setup, wait_for_all_checks
from changedetectionio import html_tools

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
     <p>new ignore stuff</p>
     <p>out of stock</p>
     <p>blah</p>
     </body>
     </html>

    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)


# Is the same but includes ZZZZZ, 'ZZZZZ' is the last line in ignore_text
def set_modified_response_minus_block_text():
    test_return_data = """<html>
       <body>
     Some NEW nice initial text<br>
     <p>Which is across multiple lines</p>
     <p>now on sale $2/p>
     <br>
     So let's see what happens.  <br>
     <p>new ignore stuff</p>
     <p>blah</p>
     </body>
     </html>

    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)


def test_check_block_changedetection_text_NOT_present(client, live_server, measure_memory_usage):

    live_server_setup(live_server)
    # Use a mix of case in ZzZ to prove it works case-insensitive.
    ignore_text = "out of stoCk\r\nfoobar"
    set_original_ignore_response()


    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    # Give the thread time to pick it up
    wait_for_all_checks(client)

    # Goto the edit page, add our ignore text
    # Add our URL to the import page
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"text_should_not_be_present": ignore_text,
              "url": test_url,
              'fetch_backend': "html_requests"
              },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    # Give the thread time to pick it up
    wait_for_all_checks(client)
    # Check it saved
    res = client.get(
        url_for("edit_page", uuid="first"),
    )
    assert bytes(ignore_text.encode('utf-8')) in res.data

    # Trigger a check
    client.get(url_for("form_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    wait_for_all_checks(client)

    # It should report nothing found (no new 'unviewed' class)
    res = client.get(url_for("index"))
    assert b'unviewed' not in res.data
    assert b'/test-endpoint' in res.data

    # The page changed, BUT the text is still there, just the rest of it changes, we should not see a change
    set_modified_original_ignore_response()

    # Trigger a check
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    # Give the thread time to pick it up
    wait_for_all_checks(client)

    # It should report nothing found (no new 'unviewed' class)
    res = client.get(url_for("index"))
    assert b'unviewed' not in res.data
    assert b'/test-endpoint' in res.data

    # 2548
    # Going back to the ORIGINAL should NOT trigger a change
    set_original_ignore_response()
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    res = client.get(url_for("index"))
    assert b'unviewed' not in res.data


    # Now we set a change where the text is gone AND its different content, it should now trigger
    set_modified_response_minus_block_text()
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    res = client.get(url_for("index"))
    assert b'unviewed' in res.data




    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data
