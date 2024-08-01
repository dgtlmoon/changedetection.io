#!/usr/bin/env python3

import time
from flask import url_for
from .util import live_server_setup, wait_for_all_checks


def test_basic_auth(client, live_server, measure_memory_usage):

    live_server_setup(live_server)

    # Add our URL to the import page
    test_url = url_for('test_basicauth_method', _external=True).replace("//","//myuser:mypass@")

    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data
    wait_for_all_checks(client)
    time.sleep(1)
    # Check form validation
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"include_filters": "", "url": test_url, "tags": "", "headers": "", 'fetch_backend': "html_requests"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    wait_for_all_checks(client)
    res = client.get(
        url_for("preview_page", uuid="first"),
        follow_redirects=True
    )

    assert b'myuser mypass basic' in res.data