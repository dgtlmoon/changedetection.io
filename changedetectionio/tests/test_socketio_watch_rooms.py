#!/usr/bin/env python3
"""A browser only gets per-watch events for the watches it is showing, and the page-header counters are sent at a
limited rate however many watches are being queued and checked."""

import time

from flask import url_for

from changedetectionio.realtime.socket_server import CoalescedEmit
from .util import wait_for_all_checks, delete_all_watches


def _events(socketio_client, seconds=3):
    """Everything received over the next few seconds, the counters can arrive up to an interval late"""
    received = []
    for _ in range(seconds * 4):
        received += socketio_client.get_received()
        time.sleep(0.25)
    return received


def test_watch_update_only_goes_to_pages_showing_that_watch(client, live_server, measure_memory_usage, datastore_path):
    from changedetectionio.flask_app import app
    socketio = app.extensions['socketio']
    datastore = client.application.config.get('DATASTORE')

    test_url = url_for('test_endpoint', _external=True)
    shown_uuid = datastore.add_watch(url=test_url)
    other_uuid = datastore.add_watch(url=test_url)
    wait_for_all_checks(client)

    shows_one_watch = socketio.test_client(app, flask_test_client=client)
    shows_no_watches = socketio.test_client(app, flask_test_client=client)
    assert shows_one_watch.is_connected() and shows_no_watches.is_connected()

    # A UUID that is not a watch and junk are ignored
    shows_one_watch.emit('watch-subscribe', {'uuids': [shown_uuid, 'not-a-watch', 123]})
    shows_no_watches.emit('watch-subscribe', {'uuids': 'nonsense'})
    shows_one_watch.get_received()
    shows_no_watches.get_received()

    res = client.post(
        url_for("ui.form_watch_list_checkbox_operations"),
        data={"op": "recheck", "uuids": [shown_uuid, other_uuid]},
        follow_redirects=True,
    )
    assert res.status_code == 200
    wait_for_all_checks(client)

    one = _events(shows_one_watch)
    none = _events(shows_no_watches, seconds=1)

    updated = {e['args'][0]['watch']['uuid'] for e in one if e['name'] == 'watch_update'}
    assert updated == {shown_uuid}, "Only the watch this page shows is sent to it"

    per_watch_events = {'watch_update', 'watch_small_status_comment', 'watch_bumped_favicon'}
    assert not [e for e in none if e['name'] in per_watch_events], "A page showing no watches gets no per-watch events"

    # The counters are for every page
    for name in ('queue_size', 'checking_now', 'general_stats_update'):
        assert name in {e['name'] for e in none}, f"{name} still goes to every page"

    shows_one_watch.disconnect()
    shows_no_watches.disconnect()
    delete_all_watches(client)


def test_counters_are_rate_limited():
    class FakeSocketIO:
        def start_background_task(self, target, *args):
            import threading
            thread = threading.Thread(target=target, args=args, daemon=True)
            thread.start()
            return thread

        def sleep(self, seconds):
            time.sleep(seconds)

    runs = []
    emit = CoalescedEmit(FakeSocketIO(), lambda: runs.append(time.monotonic()), interval=0.3)

    for _ in range(500):
        emit()
    assert len(runs) == 1, "The first call goes out straight away, the burst after it waits"

    time.sleep(0.6)
    assert len(runs) == 2, "The burst collapsed into one more, so the last state still lands"
    assert runs[1] - runs[0] >= 0.3

    emit()
    assert len(runs) == 3, "Quiet again, so the next one is immediate"


def test_bulk_operation_sends_only_the_rows_being_shown(client, live_server, measure_memory_usage, datastore_path):
    from changedetectionio.flask_app import app
    socketio = app.extensions['socketio']
    datastore = client.application.config.get('DATASTORE')

    test_url = url_for('test_endpoint', _external=True)
    uuids = [datastore.add_watch(url=test_url) for _ in range(6)]
    wait_for_all_checks(client)

    page = socketio.test_client(app, flask_test_client=client)
    page.emit('watch-subscribe', {'uuids': uuids[:2]})
    page.get_received()

    res = client.post(
        url_for("ui.form_watch_list_checkbox_operations"),
        data={"op": "pause", "uuids": uuids},
        follow_redirects=True,
    )
    assert b"6 watches paused" in res.data

    rows = [e['args'][0]['watch'] for e in _events(page, seconds=1) if e['name'] == 'watch_update']
    assert {r['uuid'] for r in rows} == set(uuids[:2]), "All six were paused, the page is told about the two it shows"
    assert all(r['paused'] for r in rows)

    page.disconnect()
    delete_all_watches(client)


def test_put_many_signals_once():
    from blinker import signal
    from changedetectionio import queuedWatchMetaData
    from changedetectionio.queue_handlers import RecheckPriorityQueue

    q = RecheckPriorityQueue()
    seen = {'per_watch': 0, 'batches': [], 'queue_lengths': []}

    def on_watch_check_update(*args, **kwargs):
        seen['per_watch'] += 1

    def on_watches_changed(*args, **kwargs):
        seen['batches'].append(kwargs.get('uuids'))

    def on_queue_length(*args, **kwargs):
        seen['queue_lengths'].append(kwargs.get('length'))

    signal('watch_check_update').connect(on_watch_check_update)
    signal('watches_changed').connect(on_watches_changed)
    signal('queue_length').connect(on_queue_length)
    try:
        uuids = [f"uuid-{n}" for n in range(500)]
        items = [queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': u}) for u in uuids]
        # Something more urgent in the same batch must still come out first
        items.append(queuedWatchMetaData.PrioritizedItem(priority=0, item={'uuid': 'urgent'}))
        assert q.put_many(items) == 501
    finally:
        signal('watch_check_update').disconnect(on_watch_check_update)
        signal('watches_changed').disconnect(on_watches_changed)
        signal('queue_length').disconnect(on_queue_length)

    assert seen['per_watch'] == 0, "A batch should not send one watch_check_update per item"
    assert len(seen['batches']) == 1 and sorted(seen['batches'][0]) == sorted(uuids + ['urgent'])
    assert seen['queue_lengths'] == [501]

    first = q.get(block=False)
    assert first.item['uuid'] == 'urgent'
    assert first.item.get('enqueued_at'), "Batch items carry the enqueue time like put() gives them"
    # Every item is retrievable, each one has its notification
    for _ in range(500):
        q.get(block=False)
    assert q.qsize() == 0
    assert q.put_many([]) == 0
