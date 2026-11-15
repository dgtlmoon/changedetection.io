#!/usr/bin/env python3
"""Whatever a check was queued with (the queue item's `item` dict) reaches the processor and the fetcher.

That is how a one-shot option works: it applies to that one check only and is never stored on the watch.
'record_har' is the first one.
"""
import json
import os
import zipfile

from flask import url_for

from changedetectionio import queuedWatchMetaData, worker_pool
from changedetectionio.flask_app import update_q
from .util import set_original_response, wait_for_all_checks


def test_one_shot_record_har_from_queue_item(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    monkeypatch.delenv('HAR_UUID_RECORD', raising=False)
    set_original_response(datastore_path=datastore_path)

    datastore = live_server.app.config['DATASTORE']
    test_url = url_for('test_endpoint', _external=True)
    uuid = datastore.add_watch(url=test_url)
    har_zip = os.path.join(datastore.data['watching'][uuid].data_dir, 'har-record.zip')

    # An ordinary check records nothing
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    assert not os.path.isfile(har_zip)

    # Queued with the option, this check is recorded
    worker_pool.queue_item_async_safe(
        update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': uuid, 'record_har': True}))
    wait_for_all_checks(client)
    assert os.path.isfile(har_zip), "The fetcher never saw 'record_har' from the queue item"
    with zipfile.ZipFile(har_zip) as z:
        entry = json.loads(z.read('har-record.har'))['log']['entries'][-1]
    assert entry['request']['url'] == test_url
    assert entry['response']['status'] == 200

    # One shot: nothing was stored on the watch, so the next ordinary check does not record again
    assert 'record_har' not in datastore.data['watching'][uuid]
    os.unlink(har_zip)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    assert not os.path.isfile(har_zip)

    client.post(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
