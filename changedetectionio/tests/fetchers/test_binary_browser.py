#!/usr/bin/env python3

"""A browser fetcher watching a file Chrome downloads (.msi etc) - the snapshot describes the file
itself, hashed by sockpuppetbrowser (SockPuppet.* CDP methods, see cdp_downloads.py), so any change
to its bytes is a change. A browser without that support gives a clear error instead."""

import hashlib
import os
from flask import url_for
from ..util import wait_for_all_checks


def _cdio(url):
    # The browser runs in another container in CI and reaches the test server as 'cdio'
    return url.replace('localhost.localdomain', 'cdio').replace('localhost', 'cdio')


def _serve(datastore_path, data):
    with open(os.path.join(datastore_path, "endpoint-binary.bin"), 'wb') as f:
        f.write(data)


def _recheck(client):
    res = client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
    assert b'Queued 1 watch for rechecking.' in res.data
    wait_for_all_checks(client)


def test_binary_download_in_browser_fetcher(client, live_server, measure_memory_usage, datastore_path):
    assert os.getenv('PLAYWRIGHT_DRIVER_URL'), "Needs PLAYWRIGHT_DRIVER_URL set for this test"

    res = client.post(
        url_for("settings.settings_page"),
        data={
            "application-empty_pages_are_a_change": "",
            "requests-time_between_check-minutes": 180,
            'application-fetch_backend': "html_webdriver",
        },
        follow_redirects=True
    )
    assert b"Settings updated." in res.data

    first = os.urandom(2 * 1024 * 1024 + 3)
    _serve(datastore_path, first)

    test_url = _cdio(url_for('test_binary_endpoint', filename='driver.msi', content_type='application/x-msi', _external=True))
    res = client.post(url_for("imports.import_page"), data={"urls": test_url}, follow_redirects=True)
    assert b"1 Imported" in res.data
    wait_for_all_checks(client)

    uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))
    watch = live_server.app.config['DATASTORE'].data['watching'][uuid]

    if watch.get('last_error') and "can't hand downloads back" in watch.get('last_error'):
        # Not a sockpuppetbrowser with the downloads API, the error says what to do
        assert not watch.history_n
        return

    assert not watch.get('last_error'), watch.get('last_error')
    assert watch.history_n == 1
    snapshot = watch.get_history_snapshot(timestamp=list(watch.history.keys())[-1])
    assert snapshot.strip() == (f"Binary file detected - application/x-msi - {len(first):,} bytes - "
                                f"SHA256 {hashlib.sha256(first).hexdigest()}")

    # Same file again - no change
    _recheck(client)
    assert not watch.get('last_error'), watch.get('last_error')
    assert watch.history_n == 1

    # Different file - a change
    _serve(datastore_path, os.urandom(1000))
    _recheck(client)
    assert not watch.get('last_error'), watch.get('last_error')
    assert watch.history_n == 2
    assert 'Binary file detected - application/x-msi - 1,000 bytes' in watch.get_history_snapshot(
        timestamp=list(watch.history.keys())[-1])
