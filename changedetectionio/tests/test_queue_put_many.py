#!/usr/bin/env python3
"""Queueing a large selection goes in as one batch with one UI event, not a signal (and a full recount of every
watch) per item."""

import time

from blinker import signal
from flask import url_for

from changedetectionio import queuedWatchMetaData
from changedetectionio.queue_handlers import RecheckPriorityQueue
from .util import wait_for_all_checks


def test_put_many_signals_once():
    q = RecheckPriorityQueue()
    seen = {'per_watch': 0, 'batches': [], 'queue_lengths': []}

    def on_watch_check_update(*args, **kwargs):
        seen['per_watch'] += 1

    def on_watches_queued(*args, **kwargs):
        seen['batches'].append(kwargs.get('uuids'))

    def on_queue_length(*args, **kwargs):
        seen['queue_lengths'].append(kwargs.get('length'))

    signal('watch_check_update').connect(on_watch_check_update)
    signal('watches_queued').connect(on_watches_queued)
    signal('queue_length').connect(on_queue_length)
    try:
        uuids = [f"uuid-{n}" for n in range(500)]
        items = [queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': u}) for u in uuids]
        # Something more urgent in the same batch must still come out first
        items.append(queuedWatchMetaData.PrioritizedItem(priority=0, item={'uuid': 'urgent'}))

        assert q.put_many(items) == 501
    finally:
        signal('watch_check_update').disconnect(on_watch_check_update)
        signal('watches_queued').disconnect(on_watches_queued)
        signal('queue_length').disconnect(on_queue_length)

    assert seen['per_watch'] == 0, "A batch should not send one watch_check_update per item"
    assert len(seen['batches']) == 1 and sorted(seen['batches'][0]) == sorted(uuids + ['urgent'])
    assert seen['queue_lengths'] == [501]

    assert q.qsize() == 501
    assert sorted(q.get_queued_uuids()) == sorted(uuids + ['urgent'])

    first = q.get(block=False)
    assert first.item['uuid'] == 'urgent'
    assert first.item.get('enqueued_at'), "Batch items carry the enqueue time like put() gives them"
    # Every item is retrievable, each one has its notification
    for _ in range(500):
        q.get(block=False)
    assert q.qsize() == 0

    assert q.put_many([]) == 0


def test_checkbox_recheck_uses_the_batch(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config.get('DATASTORE')
    test_url = url_for('test_endpoint', _external=True)
    uuids = [datastore.add_watch(url=test_url) for _ in range(3)]
    wait_for_all_checks(client)

    checked_before = {u: datastore.data['watching'][u]['last_checked'] for u in uuids}
    batches = []

    def on_watches_queued(*args, **kwargs):
        batches.append(kwargs.get('uuids'))

    signal('watches_queued').connect(on_watches_queued)
    try:
        time.sleep(1)
        # The same watch ticked twice and one that does not exist are not queued
        res = client.post(
            url_for("ui.form_watch_list_checkbox_operations"),
            data={"op": "recheck", "uuids": uuids + [uuids[0], "not-a-watch"]},
            follow_redirects=True,
        )
        assert b"3 watches queued for rechecking" in res.data
    finally:
        signal('watches_queued').disconnect(on_watches_queued)

    assert len(batches) == 1 and sorted(batches[0]) == sorted(uuids)

    wait_for_all_checks(client)
    for u in uuids:
        assert datastore.data['watching'][u]['last_checked'] > checked_before[u], "Each selected watch was rechecked"
