#!/usr/bin/python3

import time

from flask import url_for
from . util import live_server_setup

from ..html_tools import *

def test_setup(live_server):
    live_server_setup(live_server)


def test_error_handler(client, live_server):


    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URL to the import page
    test_url = url_for('test_endpoint',
                       status_code=403,
                       _external=True)
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(3)


    res = client.get(url_for("index"))
    assert b'unviewed' not in res.data
    assert b'Status Code 403' in res.data
    assert bytes("just now".encode('utf-8')) in res.data

# Just to be sure error text is properly handled
def test_error_text_handler(client, live_server):
    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URL to the import page
    res = client.post(
        url_for("import_page"),
        data={"urls": "https://errorfuldomainthatnevereallyexists12356.com"},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(3)

    res = client.get(url_for("index"))
    assert b'Name or service not known' in res.data
    assert bytes("just now".encode('utf-8')) in res.data

