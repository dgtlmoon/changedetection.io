#!/usr/bin/env python3

"""The browser fetchers must judge a fetch on the document they end up extracting.

Plenty of sites answer the first request with an interstitial carrying an error status and a
client-side redirect, then serve the real page. Judging the fetch on the first navigation fails a
watch whose content is present and fine (reported against fotokoch.de: 503 + meta refresh -> 200),
and on the pyppeteer fetcher a replaced document used to hang goto() until the hard processing
timeout because its navigation watcher is bound to the loaderId it started on.
"""

import os
from flask import url_for
from ..util import wait_for_all_checks


def _cdio(url):
    # The browser runs in another container in CI and reaches the test server as 'cdio'
    return url.replace('localhost.localdomain', 'cdio').replace('localhost', 'cdio')


def test_interstitial_redirect_is_followed(client, live_server, measure_memory_usage, datastore_path):
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

    test_url = _cdio(url_for('test_interstitial', key='renav', _external=True))

    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data
    wait_for_all_checks(client)

    # The interstitial answered 503, so judging the first navigation would have failed the watch
    uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))
    watch = live_server.app.config['DATASTORE'].data['watching'][uuid]
    assert not watch.get('last_error'), \
        f"Watch was judged on the interstitial instead of the page it landed on: {watch.get('last_error')}"

    res = client.get(url_for("watchlist.index"))
    assert b'Error - 503' not in res.data

    assert watch.history_n >= 1, "Fetch succeeded but no snapshot was stored"
    snapshot = watch.get_history_snapshot(list(watch.history.keys())[-1])
    assert 'The real page content is here' in snapshot
    assert 'Browser check in progress' not in snapshot

    client.post(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
