#!/usr/bin/python3

import time
from flask import url_for
from . util import live_server_setup

def test_setup(live_server):
    live_server_setup(live_server)


def set_response_data(test_return_data):
    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)


def test_snapshot_api_detects_change(client, live_server):
    test_return_data = "Some initial text"

    test_return_data_modified = "Some NEW nice initial text"

    sleep_time_for_fetch_thread = 3

    set_response_data(test_return_data)

    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', content_type="text/plain",
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
    time.sleep(sleep_time_for_fetch_thread)

    res = client.get(
        url_for("api_snapshot", uuid="first"),
        follow_redirects=True
    )

    assert test_return_data.encode() == res.data

    #  Make a change
    set_response_data(test_return_data_modified)

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)
    # Give the thread time to pick it up
    time.sleep(sleep_time_for_fetch_thread)

    res = client.get(
        url_for("api_snapshot", uuid="first"),
        follow_redirects=True
    )

    assert test_return_data_modified.encode() == res.data

def test_snapshot_api_invalid_uuid(client, live_server):

    res = client.get(
        url_for("api_snapshot", uuid="invalid"),
        follow_redirects=True
    )

    assert res.status_code == 400

