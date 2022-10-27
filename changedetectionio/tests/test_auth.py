#!/usr/bin/python3

import time
from flask import url_for
from . util import live_server_setup

def test_basic_auth(client, live_server):

    live_server_setup(live_server)
    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URL to the import page
    test_url = url_for('test_basicauth_method', _external=True).replace("//","//myuser:mypass@")

    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    # Check form validation
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"css_filter": "", "url": test_url, "tag": "", "headers": "", 'fetch_backend': "html_requests"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    # Trigger a check
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    time.sleep(1)
    res = client.get(
        url_for("preview_page", uuid="first"),
        follow_redirects=True
    )

    assert b'myuser mypass basic' in res.data