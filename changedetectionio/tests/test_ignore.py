#!/usr/bin/env python3

import time
from flask import url_for
from .util import live_server_setup, wait_for_all_checks
from changedetectionio import html_tools
from . util import  extract_UUID_from_client

def set_original_ignore_response():
    test_return_data = """<html>
       <body>
     Some initial text<br>
     <p>Which is across multiple lines</p>
     <br>
     So let's see what happens.  <br>
     <p>oh yeah 456</p>
     </body>
     </html>

    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)


def test_ignore(client, live_server, measure_memory_usage):
   #  live_server_setup(live_server) # Setup on conftest per function
    set_original_ignore_response()
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    # Give the thread time to pick it up
    wait_for_all_checks(client)
    uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))
    # use the highlighter endpoint
    res = client.post(
        url_for("ui.ui_edit.highlight_submit_ignore_url", uuid=uuid),
        data={"mode": 'digit-regex', 'selection': 'oh yeah 123'},
        follow_redirects=True
    )

    res = client.get(url_for("ui.ui_edit.edit_page", uuid=uuid))
    # should be a regex now
    assert b'/oh\ yeah\ \d+/' in res.data

    # Should return a link
    assert b'href' in res.data

    # It should not be in the preview anymore
    res = client.get(url_for("ui.ui_views.preview_page", uuid=uuid))
    assert b'<div class="ignored">oh yeah 456' not in res.data

    # Should be in base.html
    assert b'csrftoken' in res.data

