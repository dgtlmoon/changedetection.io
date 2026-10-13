#!/usr/bin/env python3

"""Binary files (see content_types.py) - the snapshot describes the file itself, so any change
to its bytes is a change, and nothing of the file's bytes is decoded as text."""

import hashlib
import os
from flask import url_for
from .util import wait_for_all_checks


def _serve(datastore_path, data):
    with open(os.path.join(datastore_path, "endpoint-binary.bin"), 'wb') as f:
        f.write(data)


def _recheck(client):
    res = client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
    assert b'Queued 1 watch for rechecking.' in res.data
    wait_for_all_checks(client)


def _check_binary_watch(client, live_server, datastore_path, test_url, content_type):
    first = os.urandom(3 * 1024 * 1024 + 7)
    _serve(datastore_path, first)

    datastore = live_server.app.config['DATASTORE']
    uuid = datastore.add_watch(url=test_url)
    client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    watch = datastore.data['watching'][uuid]
    assert not watch.get('last_error'), watch.get('last_error')
    assert watch.history_n == 1
    snapshot = watch.get_history_snapshot(timestamp=list(watch.history.keys())[-1])
    assert snapshot.strip() == (f"Binary file detected - {content_type} - {len(first):,} bytes - "
                                f"SHA256 {hashlib.sha256(first).hexdigest()}")

    # Not kept (keep_last_versions is 0), and no pointless .html.br of the checksum either
    assert not [f for f in os.listdir(watch.data_dir) if f.split('.')[0].isdigit()]

    # Same file again - no change
    _recheck(client)
    assert watch.history_n == 1

    # One byte different - a change
    _serve(datastore_path, first[:-1] + bytes([first[-1] ^ 0xFF]))
    _recheck(client)
    assert not watch.get('last_error'), watch.get('last_error')
    assert watch.history_n == 2


def test_binary_by_content_type(client, live_server, measure_memory_usage, datastore_path):
    test_url = url_for('test_binary_endpoint', filename='driver', content_type='application/x-msi', _external=True)
    _check_binary_watch(client, live_server, datastore_path, test_url, 'application/x-msi')


def test_binary_by_url_extension(client, live_server, measure_memory_usage, datastore_path):
    # The server says nothing useful, the URL's extension decides
    test_url = url_for('test_binary_endpoint', filename='setup.exe', _external=True)
    _check_binary_watch(client, live_server, datastore_path, test_url, 'application/x-msdownload')


def test_image_is_still_the_screenshot(client, live_server, measure_memory_usage, datastore_path):
    with open("static/images/avatar-256x256.png", 'rb') as f:
        png = f.read()
    _serve(datastore_path, png)

    datastore = live_server.app.config['DATASTORE']
    uuid = datastore.add_watch(url=url_for('test_binary_endpoint', filename='image', content_type='image/png', _external=True))
    client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    watch = datastore.data['watching'][uuid]
    assert not watch.get('last_error'), watch.get('last_error')
    assert 'Binary file detected - image/png' in watch.get_history_snapshot(timestamp=list(watch.history.keys())[-1])
    with open(watch.get_screenshot(), 'rb') as f:
        assert f.read() == png

