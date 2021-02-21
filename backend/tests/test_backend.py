#!/usr/bin/python3

import time
import pytest
from flask import url_for
from urllib.request import urlopen

def set_original_response():

    test_return_data = """<html>
       <body>
     Some initial text</br>
     <p>Which is across multiple lines</p>
     </br>
     So let's see what happens.  </br>
     </body>
     </html>

    """

    with open("test-datastore/output.txt", "w") as f:
        f.write(test_return_data)


def set_modified_response():
    test_return_data = """<html>
       <body>
     Some initial text</br>
     <p>which has this one new line</p>
     </br>
     So let's see what happens.  </br>
     </body>
     </html>

    """

    with open("test-datastore/output.txt", "w") as f:
        f.write(test_return_data)


def test_check_basic_change_detection_functionality(client, live_server):
    sleep_time_for_fetch_thread = 3

    @live_server.app.route('/test-endpoint')

    def test_endpoint():
        # Tried using a global var here but didn't seem to work, so reading from a file instead.
        with open("test-datastore/output.txt", "r") as f:
            return f.read()

    set_original_response()

    live_server.start()

    # Add our URL to the import page
    res = client.post(
        url_for("import_page"),
        data={"urls": url_for('test_endpoint', _external=True)},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    client.get(url_for("api_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(sleep_time_for_fetch_thread)

    # It should report nothing found (no new 'unviewed' class)
    res = client.get(url_for("index"))
    assert b'unviewed' not in res.data
    assert b'test-endpoint' in res.data

    # Give the thread time to pick it up
    time.sleep(sleep_time_for_fetch_thread)
    res = client.get(url_for("index"))

    assert b'unviewed' not in res.data

#####################


    # Make a change
    set_modified_response()

    res = urlopen(url_for('test_endpoint', _external=True))
    assert b'which has this one new line' in res.read()


    # Force recheck
    res = client.get(url_for("api_watch_checknow"), follow_redirects=True)
    assert b'1 watches are rechecking.' in res.data

    time.sleep(sleep_time_for_fetch_thread)

    # Now something should be ready, indicated by having a 'unviewed' class
    res = client.get(url_for("index"))
    assert b'unviewed' in res.data

