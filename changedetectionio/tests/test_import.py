#!/usr/bin/python3

import time

from flask import url_for

from .util import live_server_setup
def test_setup(client, live_server):
    live_server_setup(live_server)

def test_import(client, live_server):
    # Give the endpoint time to spin up
    time.sleep(1)

    res = client.post(
        url_for("import_page"),
        data={
            "urls": """https://example.com
https://example.com tag1
https://example.com tag1, other tag"""
        },
        follow_redirects=True,
    )
    assert b"3 Imported" in res.data
    assert b"tag1" in res.data
    assert b"other tag" in res.data



def test_import_skip_url(client, live_server):


    # Give the endpoint time to spin up
    time.sleep(1)

    res = client.post(
        url_for("import_page"),
        data={
            "urls": """https://example.com
:ht000000broken
"""
        },
        follow_redirects=True,
    )
    assert b"1 Imported" in res.data
    assert b"ht000000broken" in res.data
    assert b"1 Skipped" in res.data
