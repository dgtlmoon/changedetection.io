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


def test_har_record_env_writes_har_zip(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    """HAR_UUID_RECORD=<uuid> saves the network traffic of that watch's fetch to har-record.zip"""
    import json
    import zipfile

    assert os.getenv('PLAYWRIGHT_DRIVER_URL'), "Needs PLAYWRIGHT_DRIVER_URL set for this test"

    client.post(
        url_for("settings.settings_page"),
        data={
            "application-empty_pages_are_a_change": "",
            "requests-time_between_check-minutes": 180,
            'application-fetch_backend': "html_webdriver",
        },
        follow_redirects=True
    )

    datastore = live_server.app.config['DATASTORE']
    recorded_url = _cdio(url_for('test_interstitial', key='har-on', _external=True))
    recorded = datastore.add_watch(url=recorded_url)
    not_recorded = datastore.add_watch(url=_cdio(url_for('test_interstitial', key='har-off', _external=True)))

    # Upper-cased and with a neighbour in the list, the match is case insensitive
    monkeypatch.setenv('HAR_UUID_RECORD', f"not-a-real-uuid, {recorded.upper()}")

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    watch = datastore.data['watching'][recorded]
    assert not watch.get('last_error'), watch.get('last_error')

    har_zip = os.path.join(watch.data_dir, 'har-record.zip')
    assert os.path.isfile(har_zip), "HAR_UUID_RECORD listed this watch but nothing was recorded"
    with zipfile.ZipFile(har_zip) as z:
        har = json.loads(z.read('har-record.har'))

    # Shown by the "HAR TEST OUTPUT" step in CI (pytest -s), so a human can eyeball what was recorded
    lines = ["=== HAR TEST OUTPUT ===",
             f"HAR {har['log']['version']} - {len(har['log']['entries'])} entries, zip is {os.path.getsize(har_zip)} bytes"]
    for e in har['log']['entries']:
        lines.append(f"{e['request']['method']} {e['response']['status']} {e['request']['url']} "
                     f"[{e.get('_resourceType', '')}, {e['response']['content']['mimeType']}, "
                     f"{e['response']['content']['size']} bytes, {e['time']}ms]")
        lines += [f"   > {h['name']}: {h['value']}" for h in e['request']['headers']]
        lines += [f"   < {h['name']}: {h['value']}" for h in e['response']['headers']]
    lines.append("=== END HAR TEST OUTPUT ===")
    print("\n".join(lines), flush=True)

    documents = [e for e in har['log']['entries'] if e['request']['url'] == recorded_url]
    # Both hops of the interstitial are in there, which is the whole point of having the recording
    assert [e['response']['status'] for e in documents] == [503, 200]
    body = documents[-1]['response']['content']
    text = body.get('text', '')
    if body.get('encoding') == 'base64':
        import base64
        text = base64.b64decode(text).decode()
    assert 'The real page content is here' in text

    assert not os.path.isfile(os.path.join(datastore.data['watching'][not_recorded].data_dir, 'har-record.zip')), \
        "A watch that is not listed in HAR_UUID_RECORD must not be recorded"

    # And the same recording is what "Download watch data package" hands out
    import io
    res = client.get(url_for("ui.ui_edit.watch_get_data_package", uuid=recorded))
    package = zipfile.ZipFile(io.BytesIO(res.data))
    with open(har_zip, 'rb') as f:
        assert package.read(f"{recorded}/har-record.zip") == f.read()

    client.post(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
