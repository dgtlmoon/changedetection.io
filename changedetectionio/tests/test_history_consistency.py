#!/usr/bin/env python3

import time
import os
import json
import logging
from flask import url_for
from .util import live_server_setup, wait_for_all_checks
from urllib.parse import urlparse, parse_qs

def test_consistent_history(client, live_server, measure_memory_usage):
   #  live_server_setup(live_server) # Setup on conftest per function
    workers = int(os.getenv("FETCH_WORKERS", 10))
    r = range(1, 10+workers)

    for one in r:
        test_url = url_for('test_endpoint', content_type="text/html", content=str(one), _external=True)
        res = client.post(
            url_for("imports.import_page"),
            data={"urls": test_url},
            follow_redirects=True
        )

        assert b"1 Imported" in res.data

    wait_for_all_checks(client)

    # Essentially just triggers the DB write/update
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-empty_pages_are_a_change": "",
              "requests-time_between_check-minutes": 180,
              'application-fetch_backend': "html_requests"},
        follow_redirects=True
    )
    assert b"Settings updated." in res.data


    time.sleep(2)

    json_db_file = os.path.join(live_server.app.config['DATASTORE'].datastore_path, 'url-watches.json')

    json_obj = None
    with open(json_db_file, 'r') as f:
        json_obj = json.load(f)

    # assert the right amount of watches was found in the JSON
    assert len(json_obj['watching']) == len(r), "Correct number of watches was found in the JSON"
    i=0
    # each one should have a history.txt containing just one line
    for w in json_obj['watching'].keys():
        i+=1
        history_txt_index_file = os.path.join(live_server.app.config['DATASTORE'].datastore_path, w, 'history.txt')
        assert os.path.isfile(history_txt_index_file), f"History.txt should exist where I expect it at {history_txt_index_file}"

        # Same like in model.Watch
        with open(history_txt_index_file, "r") as f:
            tmp_history = dict(i.strip().split(',', 2) for i in f.readlines())
            assert len(tmp_history) == 1, "History.txt should contain 1 line"

        # Should be two files,. the history.txt , and the snapshot.txt
        files_in_watch_dir = os.listdir(os.path.join(live_server.app.config['DATASTORE'].datastore_path, w))

        # Find the snapshot one
        for fname in files_in_watch_dir:
            if fname != 'history.txt' and 'html' not in fname:
                # contents should match what we requested as content returned from the test url
                with open(os.path.join(live_server.app.config['DATASTORE'].datastore_path, w, fname), 'r') as snapshot_f:
                    contents = snapshot_f.read()
                    watch_url = json_obj['watching'][w]['url']
                    u = urlparse(watch_url)
                    q = parse_qs(u[4])
                    assert q['content'][0] == contents.strip(), f"Snapshot file {fname} should contain {q['content'][0]}"



        assert len(files_in_watch_dir) == 3, "Should be just three files in the dir, html.br snapshot, history.txt and the extracted text snapshot"

    json_db_file = os.path.join(live_server.app.config['DATASTORE'].datastore_path, 'url-watches.json')
    with open(json_db_file, 'r') as f:
        assert '"default"' not in f.read(), "'default' probably shouldnt be here, it came from when the 'default' Watch vars were accidently being saved"


def test_check_text_history_view(client, live_server):

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write("<html>test-one</html>")

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    # Give the thread time to pick it up
    wait_for_all_checks(client)

    # Set second version, Make a change
    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write("<html>test-two</html>")

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.get(url_for("ui.ui_views.diff_history_page", uuid="first"))
    assert b'test-one' in res.data
    assert b'test-two' in res.data

    # Set third version, Make a change
    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write("<html>test-three</html>")

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # It should remember the last viewed time, so the first difference is not shown
    res = client.get(url_for("ui.ui_views.diff_history_page", uuid="first"))
    assert b'test-three' in res.data
    assert b'test-two' in res.data
    assert b'test-one' not in res.data

    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data
