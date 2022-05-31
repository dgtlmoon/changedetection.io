#!/usr/bin/python3

import time
import os
import json
from flask import url_for
from .util import live_server_setup


def test_consistent_history(client, live_server):
    live_server_setup(live_server)

    # Give the endpoint time to spin up
    time.sleep(1)
    r = range(97, 110)

    for one in r:
        test_url = url_for('test_endpoint', content_type="text/html", content=str(chr(one)), _external=True)
        res = client.post(
            url_for("import_page"),
            data={"urls": test_url},
            follow_redirects=True
        )

        assert b"1 Imported" in res.data

    time.sleep(3)
    while True:
        res = client.get(url_for("index"))
        if b'Checking now' not in res.data:
            break
        time.sleep(0.5)

    # Essentially just triggers the DB write/update
    res = client.post(
        url_for("settings_page"),
        data={"application-empty_pages_are_a_change": "",
              "requests-time_between_check-minutes": 180,
              'application-fetch_backend': "html_requests"},
        follow_redirects=True
    )
    assert b"Settings updated." in res.data

    # Give it time to write it out
    time.sleep(3)
    json_db_file = os.path.join(live_server.app.config['DATASTORE'].datastore_path, 'url-watches.json')

    json_obj = None
    with open(json_db_file, 'r') as f:
        json_obj = json.load(f)

    # assert the right amount of watches was found in the JSON
    assert len(json_obj['watching']) == len(r), "Correct number of watches was found in the JSON"

    # each one should have a history.txt containing just one line
    for w in json_obj['watching'].keys():
        history_txt_index_file = os.path.join(live_server.app.config['DATASTORE'].datastore_path, w, 'history.txt')
        assert os.path.isfile(history_txt_index_file), "History.txt should exist where I expect it"

        # Same like in model.Watch
        with open(history_txt_index_file, "r") as f:
            tmp_history = dict(i.strip().split(',', 2) for i in f.readlines())
            assert len(tmp_history) == 1, "History.txt should contain 1 line"

        # Should be two files,. the history.txt , and the snapshot.txt
        assert len(os.listdir(os.path.join(live_server.app.config['DATASTORE'].datastore_path,
                                           w))) == 2, "Should be just two files in the dir, history.txt and the snapshot"
