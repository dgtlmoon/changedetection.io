#!/usr/bin/env python3

import time
import os
import json
from flask import url_for
from loguru import logger
from .. import strtobool
from .util import wait_for_all_checks, delete_all_watches
import brotli


def test_consistent_history(client, live_server, measure_memory_usage, datastore_path):

    uuids = set()
    sys_fetch_workers = int(os.getenv("FETCH_WORKERS", 10))
    workers = range(1, sys_fetch_workers)
    now = time.time()

    for one in workers:
        if strtobool(os.getenv("TEST_WITH_BROTLI")):
            # A very long string that WILL trigger Brotli compression of the snapshot
            # BROTLI_COMPRESS_SIZE_THRESHOLD should be set to say 200
            from ..model.Watch import BROTLI_COMPRESS_SIZE_THRESHOLD
            content = str(one) + "x" + str(one) * (BROTLI_COMPRESS_SIZE_THRESHOLD + 10)
        else:
            # Just enough to test datastore
            content = str(one)+'x'

        test_url = url_for('test_endpoint', content_type="text/html", content=content, _external=True)
        uuids.add(client.application.config.get('DATASTORE').add_watch(url=test_url, extras={'title': str(one)}))

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    wait_for_all_checks(client)
    duration = time.time() - now
    per_worker = duration/sys_fetch_workers
    if sys_fetch_workers < 20:
        per_worker_threshold=0.6
    elif sys_fetch_workers < 50:
        per_worker_threshold = 0.8
    else:
        per_worker_threshold = 1.5

    logger.debug(f"All fetched in {duration:.2f}s, {per_worker}s per worker")
    # Problematic on github
    #assert per_worker < per_worker_threshold, f"If concurrency is working good, no blocking async problems, each worker ({sys_fetch_workers} workers) should have done his job in under {per_worker_threshold}s, got {per_worker:.2f}s per worker, total duration was {duration:.2f}s"

    # Essentially just triggers the DB write/update
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-empty_pages_are_a_change": "",
              "requests-time_between_check-minutes": 180,
              'application-fetch_backend': "html_requests"},
        follow_redirects=True
    )
    assert b"Settings updated." in res.data

    # Wait for the sync DB save to happen
    time.sleep(2)

    # Check which format is being used
    datastore_path = live_server.app.config['DATASTORE'].datastore_path
    changedetection_json = os.path.join(datastore_path, 'changedetection.json')
    url_watches_json = os.path.join(datastore_path, 'url-watches.json')

    json_obj = {'watching': {}}

    if os.path.exists(changedetection_json):
        # New format: individual watch.json files
        logger.info("Testing with new format (changedetection.json + individual watch.json)")

        # Load each watch.json file
        for uuid in live_server.app.config['DATASTORE'].data['watching'].keys():
            watch_json_file = os.path.join(datastore_path, uuid, 'watch.json')
            assert os.path.isfile(watch_json_file), f"watch.json should exist at {watch_json_file}"

            with open(watch_json_file, 'r', encoding='utf-8') as f:
                json_obj['watching'][uuid] = json.load(f)
    else:
        # Legacy format: url-watches.json
        logger.info("Testing with legacy format (url-watches.json)")
        with open(url_watches_json, 'r', encoding='utf-8') as f:
            json_obj = json.load(f)

    # assert the right amount of watches was found in the JSON
    assert len(json_obj['watching']) == len(workers), "Correct number of watches was found in the JSON"

    i = 0
    # each one should have a history.txt containing just one line
    for w in json_obj['watching'].keys():
        i += 1
        history_txt_index_file = os.path.join(live_server.app.config['DATASTORE'].datastore_path, w, 'history.txt')
        assert os.path.isfile(history_txt_index_file), f"History.txt should exist where I expect it at {history_txt_index_file}"

        # Should be no errors (could be from brotli etc)
        assert not live_server.app.config['DATASTORE'].data['watching'][w].get('last_error')

        # Same like in model.Watch
        with open(history_txt_index_file, "r") as f:
            tmp_history = dict(i.strip().split(',', 2) for i in f.readlines())
            assert len(tmp_history) == 1, "History.txt should contain 1 line"

        # Should be two files,. the history.txt , and the snapshot.txt
        files_in_watch_dir = os.listdir(os.path.join(live_server.app.config['DATASTORE'].datastore_path, w))

        # Find the snapshot one
        for fname in files_in_watch_dir:
            if fname != 'history.txt' and fname != 'watch.json' and fname != 'last-checksum.txt' and 'html' not in fname:
                if strtobool(os.getenv("TEST_WITH_BROTLI")):
                    assert fname.endswith('.br'), "Forced TEST_WITH_BROTLI then it should be a .br filename"

                full_snapshot_history_path = os.path.join(live_server.app.config['DATASTORE'].datastore_path, w, fname)
                # contents should match what we requested as content returned from the test url
                if fname.endswith('.br'):
                    with open(full_snapshot_history_path, 'rb') as f:
                        contents = brotli.decompress(f.read()).decode('utf-8')
                else:
                    with open(full_snapshot_history_path, 'r') as snapshot_f:
                        contents = snapshot_f.read()

                watch_title = json_obj['watching'][w]['title']
                assert json_obj['watching'][w]['title'], "Watch should have a title set"
                assert contents.startswith(watch_title + "x"), f"Snapshot contents in file {fname} should start with '{watch_title}x', got '{contents}'"

        # With new format, we have watch.json, so 4 files minimum
        # Note: last-checksum.txt may or may not exist - it gets cleared by settings changes,
        # and this test changes settings before checking files
        # This assertion should be AFTER the loop, not inside it
        if os.path.exists(changedetection_json):
            # 4 required files: watch.json, html.br, history.txt, extracted text snapshot
            # last-checksum.txt is optional (cleared by settings changes in this test)
            assert len(files_in_watch_dir) >= 4 and len(files_in_watch_dir) <= 5, f"Should be 4-5 files in the dir with new format (last-checksum.txt is optional). Found {len(files_in_watch_dir)}: {files_in_watch_dir}"
        else:
            # 3 required files: html.br, history.txt, extracted text snapshot
            # last-checksum.txt is optional
            assert len(files_in_watch_dir) >= 3 and len(files_in_watch_dir) <= 4, f"Should be 3-4 files in the dir with legacy format (last-checksum.txt is optional). Found {len(files_in_watch_dir)}: {files_in_watch_dir}"

    # Check that 'default' Watch vars aren't accidentally being saved
    if os.path.exists(changedetection_json):
        # New format: check all individual watch.json files
        for uuid in json_obj['watching'].keys():
            watch_json_file = os.path.join(datastore_path, uuid, 'watch.json')
            with open(watch_json_file, 'r', encoding='utf-8') as f:
                assert '"default"' not in f.read(), f"'default' probably shouldnt be here in {watch_json_file}, it came from when the 'default' Watch vars were accidently being saved"
    else:
        # Legacy format: check url-watches.json
        with open(url_watches_json, 'r', encoding='utf-8') as f:
            assert '"default"' not in f.read(), "'default' probably shouldnt be here, it came from when the 'default' Watch vars were accidently being saved"


    delete_all_watches(client)

def test_check_text_history_view(client, live_server, measure_memory_usage, datastore_path):

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write("<html>test-one</html>")

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    wait_for_all_checks(client)

    # Set second version, Make a change
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write("<html>test-two</html>")

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.get(url_for("ui.ui_diff.diff_history_page", uuid=uuid))
    assert b'test-one' in res.data
    assert b'test-two' in res.data

    # Set third version, Make a change
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write("<html>test-three</html>")

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # It should remember the last viewed time, so the first difference is not shown
    res = client.get(url_for("ui.ui_diff.diff_history_page", uuid="first"))
    assert b'test-three' in res.data
    assert b'test-two' in res.data
    assert b'test-one' not in res.data

    delete_all_watches(client)


def test_history_trim_global_only(client, live_server, measure_memory_usage, datastore_path):
    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    uuid = None
    limit = 3

    for i in range(0, 10):
        with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
            f.write(f"<html>test {i}</html>")
        if not uuid:
            uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
        client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
        wait_for_all_checks(client)

        if i ==8:
            watch = live_server.app.config['DATASTORE'].data['watching'][uuid]
            history_n = len(list(watch.history.keys()))
            logger.debug(f"History length should be at limit {limit} and it is {history_n}")
            assert history_n == limit

        if i == 6:
            res = client.post(
                url_for("settings.settings_page"),
                data={"application-history_snapshot_max_length": limit},
                follow_redirects=True
            )
            # It will need to detect one more change to start trimming it, which is really at 'start of 7'
            assert b'Settings updated' in res.data

    delete_all_watches(client)


def test_history_trim_global_override_in_watch(client, live_server, measure_memory_usage, datastore_path):
    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    uuid = None
    limit = 3
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-history_snapshot_max_length": 10000},
        follow_redirects=True
    )
    # It will need to detect one more change to start trimming it, which is really at 'start of 7'
    assert b'Settings updated' in res.data


    for i in range(0, 10):
        with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
            f.write(f"<html>test {i}</html>")
        if not uuid:
            uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
            res = client.post(
                url_for("ui.ui_edit.edit_page", uuid="first"),
                data={"include_filters": "", "url": test_url, "tags": "", "headers": "", 'fetch_backend': "html_requests",
                      "time_between_check_use_default": "y", "history_snapshot_max_length": str(limit)},
                follow_redirects=True
            )
            assert b"Updated watch." in res.data

            wait_for_all_checks(client)

        client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
        wait_for_all_checks(client)

        if i == 8:
            watch = live_server.app.config['DATASTORE'].data['watching'][uuid]
            history_n = len(list(watch.history.keys()))
            logger.debug(f"History length should be at limit {limit} and it is {history_n}")
            assert history_n == limit

        if i == 6:
            res = client.post(
                url_for("settings.settings_page"),
                data={"application-history_snapshot_max_length": limit},
                follow_redirects=True
            )
            # It will need to detect one more change to start trimming it, which is really at 'start of 7'
            assert b'Settings updated' in res.data

    delete_all_watches(client)

