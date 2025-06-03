#!/usr/bin/env python3

import time
from flask import url_for
from .util import live_server_setup


def set_original_ignore_response():
    test_return_data = """<html>
       <body>
     <span>The price is</span><span>$<!-- -->90<!-- -->.<!-- -->74</span>
     </body>
     </html>

    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)


def test_obfuscations(client, live_server, measure_memory_usage):
    set_original_ignore_response()
   #  live_server_setup(live_server) # Setup on conftest per function
    time.sleep(1)
    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    # Give the thread time to pick it up
    time.sleep(3)

    # Check HTML conversion detected and workd
    res = client.get(
        url_for("ui.ui_views.preview_page", uuid="first"),
        follow_redirects=True
    )

    assert b'$90.74' in res.data
