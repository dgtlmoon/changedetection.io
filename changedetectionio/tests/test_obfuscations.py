#!/usr/bin/env python3

import time
from flask import url_for
from .util import live_server_setup
import os


def set_original_ignore_response(datastore_path):
    test_return_data = """<html>
       <body>
     <span>The price is</span><span>$<!-- -->90<!-- -->.<!-- -->74</span>
     </body>
     </html>

    """

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)


def test_obfuscations(client, live_server, measure_memory_usage, datastore_path):
    set_original_ignore_response(datastore_path)
   #  live_server_setup(live_server) # Setup on conftest per function
    time.sleep(1)
    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(3)

    # Check HTML conversion detected and workd
    res = client.get(
        url_for("ui.ui_preview.preview_page", uuid="first"),
        follow_redirects=True
    )

    assert b'$90.74' in res.data
