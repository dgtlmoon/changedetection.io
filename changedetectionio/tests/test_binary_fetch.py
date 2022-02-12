#!/usr/bin/python3

import time
import secrets
from flask import url_for
from . util import live_server_setup


def test_binary_file_change(client, live_server):
    with open("test-datastore/test.bin", "wb") as f:
        f.write(secrets.token_bytes())

    live_server_setup(live_server)

    sleep_time_for_fetch_thread = 3

    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URL to the import page
    test_url = url_for('test_binaryfile_endpoint', _external=True)
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(sleep_time_for_fetch_thread)

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)

    # It should report nothing found (no new 'unviewed' class)
    res = client.get(url_for("index"))
    assert b'unviewed' not in res.data
    assert b'/test-binary-endpoint' in res.data

    #  Make a change
    with open("test-datastore/test.bin", "wb") as f:
        f.write(secrets.token_bytes())


    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(sleep_time_for_fetch_thread)

    # It should report nothing found (no new 'unviewed' class)
    res = client.get(url_for("index"))
    assert b'unviewed' in res.data
