#!/usr/bin/env python3

import time
from flask import url_for
from .util import live_server_setup, wait_for_all_checks


def test_clone_functionality(client, live_server, measure_memory_usage):

   #  live_server_setup(live_server) # Setup on conftest per function
    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write("<html><body>Some content</body></html>")

    test_url = url_for('test_endpoint', _external=True)

    # Add our URL to the import page
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data
    wait_for_all_checks(client)

    # So that we can be sure the same history doesnt carry over
    time.sleep(1)

    res = client.get(
        url_for("ui.form_clone", uuid="first"),
        follow_redirects=True
    )
    existing_uuids = set()

    for uuid, watch in live_server.app.config['DATASTORE'].data['watching'].items():
        new_uuids = set(watch.history.keys())
        duplicates = existing_uuids.intersection(new_uuids)
        assert len(duplicates) == 0
        existing_uuids.update(new_uuids)

    assert b"Cloned" in res.data
