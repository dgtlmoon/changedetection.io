"""
Tests for the queue inspection UI (blueprint/ui/queue.py).

Strategy: shut down all workers, pause the scheduler, then push synthetic
UUIDs directly into update_q. Synthetic UUIDs are immune to scheduler
interference. The HTTP test client + live_server share the same process,
so update_q is a single instance.
"""

import time
from flask import url_for


def _quiesce(live_server, timeout=3.0):
    """Pause scheduler, shut down all workers, wait for in-flight async workers
    to fully drain, clear queue. Returns (update_q, worker_pool, queuedWatchMetaData).

    The "brutal" shutdown registers stop-flags but workers blocked in
    update_q.async_get() can still complete one more pop after shutdown is
    requested. We poll for a quiet period where consecutive clear()s show no
    new items being deposited.
    """
    from changedetectionio import worker_pool, queuedWatchMetaData
    from changedetectionio.flask_app import update_q

    live_server.app.config['DATASTORE'].data['settings']['application']['all_paused'] = True
    live_server.app.set_workers(0)

    deadline = time.time() + timeout
    while time.time() < deadline:
        if worker_pool.get_worker_count() == 0:
            break
        time.sleep(0.05)
    assert worker_pool.get_worker_count() == 0, "workers did not shut down in time"

    # Push a sentinel and watch for it to remain in the queue across consecutive reads.
    # If a lingering coroutine pops it, we requeue and wait. Once it survives a settle
    # window the queue is genuinely quiescent.
    sentinel_uuid = "00000000-0000-0000-0000-0000sent1nel0"
    sentinel = queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': sentinel_uuid})

    update_q.clear()
    settle_deadline = time.time() + timeout
    while time.time() < settle_deadline:
        worker_pool.queue_item_async_safe(update_q, sentinel)
        time.sleep(0.15)
        if sentinel_uuid in update_q.get_queued_uuids():
            break
        # Was popped by a lingering worker — try again
    else:
        raise AssertionError("Could not get queue to a quiescent state")

    update_q.clear()
    return update_q, worker_pool, queuedWatchMetaData


def _push(update_q, worker_pool, qmeta, uuid, priority=1):
    ok = worker_pool.queue_item_async_safe(
        update_q,
        qmeta.PrioritizedItem(priority=priority, item={'uuid': uuid}),
    )
    assert ok, f"queue_item_async_safe returned falsy for {uuid}"


def test_queue_page_renders_when_empty(client, live_server, measure_memory_usage, datastore_path):
    """Empty queue: HTML 200, JSON shape matches contract."""
    _quiesce(live_server)

    res = client.get(url_for("ui.ui_queue.queue_page"))
    assert res.status_code == 200
    assert b"Check queue" in res.data
    # Single combined "Workers & queue" table — replaces the old separate Running/Queue tables.
    assert b"Workers" in res.data and b"queue" in res.data
    assert b"Clear Queue" in res.data
    assert b"Re-check Errored" not in res.data

    data = client.get(url_for("ui.ui_queue.queue_json")).get_json()
    for key in ("worker_count", "running_count", "queued_count", "summary", "running", "queued"):
        assert key in data
    for sub in ("immediate", "clone", "scheduled", "priority_breakdown"):
        assert sub in data["summary"]
    assert data["queued_count"] == 0
    assert data["running_count"] == 0


def test_queue_state_full_lifecycle(client, live_server, measure_memory_usage, datastore_path):
    """One consolidated test of pushed items, priority labels, deleted-watch handling, and Clear Queue.

    Combined into one test deliberately — having separate tests revealed cross-test state leakage
    (workers occasionally surviving teardown) that this single test avoids.
    """
    update_q, worker_pool, qmeta = _quiesce(live_server)

    running_uuid = "11111111-1111-1111-1111-111111111111"
    immediate_uuid = "22222222-2222-2222-2222-222222222222"
    clone_uuid = "33333333-3333-3333-3333-333333333333"
    scheduled_uuid = "44444444-4444-4444-4444-444444444444"

    # Mark one synthetic UUID as currently running.
    assert worker_pool.claim_uuid_for_processing(running_uuid, worker_id=999) is True

    # Push at three different priority classes.
    _push(update_q, worker_pool, qmeta, immediate_uuid, priority=1)
    _push(update_q, worker_pool, qmeta, clone_uuid, priority=5)
    _push(update_q, worker_pool, qmeta, scheduled_uuid, priority=99999)

    # Local sanity check: items are actually in the queue object before the HTTP read.
    queued_local = update_q.get_queued_uuids()
    assert set(queued_local) == {immediate_uuid, clone_uuid, scheduled_uuid}, \
        f"items missing from update_q after push: {queued_local}"

    try:
        # --- JSON view shows pushed state ---
        data = client.get(url_for("ui.ui_queue.queue_json")).get_json()
        assert data["worker_count"] == 0
        assert data["running_count"] == 1
        assert data["queued_count"] == 3, f"unexpected queue state: {data!r}"
        assert data["running"][0]["uuid"] == running_uuid
        # Synthetic UUIDs aren't in the datastore — should be rendered as 'gone'
        assert data["running"][0]["gone"] is True

        # --- Priority labels map correctly ---
        labels = {entry["uuid"]: entry["priority_label"] for entry in data["queued"]}
        assert labels[immediate_uuid] == "immediate"
        assert labels[clone_uuid] == "clone"
        assert labels[scheduled_uuid] == "scheduled"
        assert data["summary"]["immediate"] == 1
        assert data["summary"]["clone"] == 1
        assert data["summary"]["scheduled"] == 1

        # --- Deleted-watch placeholder ---
        for entry in data["queued"]:
            assert entry["gone"] is True
            assert entry.get("title") is None
            assert entry.get("url") is None

        # --- HTML view also surfaces the queued UUIDs ---
        html = client.get(url_for("ui.ui_queue.queue_page")).data
        for uuid in (immediate_uuid, clone_uuid, scheduled_uuid):
            assert uuid.encode("utf-8") in html

        # --- POST /queue/clear empties pending ---
        res = client.post(
            url_for("ui.ui_queue.queue_clear"),
            data={"csrf_token": "test"},
            follow_redirects=True,
        )
        assert res.status_code == 200
        assert b"Queue cleared" in res.data

        after = client.get(url_for("ui.ui_queue.queue_json")).get_json()
        assert after["queued_count"] == 0, f"queue should be empty after clear, got {after!r}"
        # The synthetic 'running' claim is untouched by Clear Queue — running checks aren't queue items.
        assert after["running_count"] == 1

    finally:
        worker_pool.release_uuid_from_processing(running_uuid, worker_id=999)
        update_q.clear()


def test_queue_includes_timestamps(client, live_server, measure_memory_usage, datastore_path):
    """Queue items carry enqueued_at; running items carry started_at."""
    update_q, worker_pool, qmeta = _quiesce(live_server)

    # Push something — enqueued_at should be ~now
    before = time.time()
    queued_uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    _push(update_q, worker_pool, qmeta, queued_uuid, priority=1)
    after = time.time()

    snap = client.get(url_for("ui.ui_queue.queue_json")).get_json()
    assert len(snap["queued"]) == 1
    ts_q = snap["queued"][0]["enqueued_at"]
    assert isinstance(ts_q, float)
    assert before <= ts_q <= after + 0.5, f"enqueued_at out of range: {ts_q!r}"

    # Claim a synthetic running uuid — started_at should be ~now
    running_uuid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    before = time.time()
    assert worker_pool.claim_uuid_for_processing(running_uuid, worker_id=999)
    after = time.time()

    snap = client.get(url_for("ui.ui_queue.queue_json")).get_json()
    running_entry = next((r for r in snap["running"] if r["uuid"] == running_uuid), None)
    assert running_entry is not None
    ts_r = running_entry["started_at"]
    assert isinstance(ts_r, float)
    assert before <= ts_r <= after + 0.5, f"started_at out of range: {ts_r!r}"

    # Release clears the timestamp
    worker_pool.release_uuid_from_processing(running_uuid, worker_id=999)
    assert worker_pool.get_uuid_started_at(running_uuid) is None

    update_q.clear()


def test_queue_pagination(client, live_server, measure_memory_usage, datastore_path):
    """Page math: per_page from settings.pager_size, total_pages, page slicing."""
    update_q, worker_pool, qmeta = _quiesce(live_server)

    # Override pager_size for this test so we don't have to push 50+ items
    live_server.app.config['DATASTORE'].data['settings']['application']['pager_size'] = 2

    uuids = [f"{i:08d}-2222-3333-4444-555555555555" for i in range(5)]
    for u in uuids:
        _push(update_q, worker_pool, qmeta, u, priority=1)

    snap1 = client.get(url_for("ui.ui_queue.queue_json")).get_json()
    assert snap1["per_page"] == 2
    assert snap1["queued_count"] == 5
    assert snap1["total_pages"] == 3
    assert snap1["page"] == 1
    assert len(snap1["queued"]) == 2

    snap2 = client.get(url_for("ui.ui_queue.queue_json") + "?page=2").get_json()
    assert snap2["page"] == 2
    assert len(snap2["queued"]) == 2

    snap3 = client.get(url_for("ui.ui_queue.queue_json") + "?page=3").get_json()
    assert snap3["page"] == 3
    assert len(snap3["queued"]) == 1, f"last page should be partial: {snap3!r}"

    # Pages cover every uuid exactly once
    all_uuids = [w["uuid"] for w in snap1["queued"] + snap2["queued"] + snap3["queued"]]
    assert sorted(all_uuids) == sorted(uuids)

    # Restore + drain
    live_server.app.config['DATASTORE'].data['settings']['application']['pager_size'] = 50
    update_q.clear()


def test_cancel_running_uuid_helper(client, live_server, measure_memory_usage, datastore_path):
    """worker_pool.cancel_running_uuid() drops tracking and returns cancelled flag."""
    update_q, worker_pool, qmeta = _quiesce(live_server)

    synth = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    assert worker_pool.claim_uuid_for_processing(synth, worker_id=999) is True
    assert worker_pool.get_uuid_started_at(synth) is not None

    # No worker_id=999 actually exists in worker_threads — the stop/remove path is
    # a no-op — but tracking still gets dropped.
    result = worker_pool.cancel_running_uuid(synth)
    assert result["cancelled"] is True
    assert result["worker_id"] == 999
    assert result["replaced"] is False  # no replacement params provided

    assert synth not in worker_pool.get_running_uuids()
    assert worker_pool.get_uuid_started_at(synth) is None

    # Cancelling something that was never running returns cancelled=False
    result2 = worker_pool.cancel_running_uuid("never-claimed")
    assert result2["cancelled"] is False
    assert result2["worker_id"] is None


def test_cancel_running_endpoint(client, live_server, measure_memory_usage, datastore_path):
    """POST /queue/cancel-running: 200 on success, 400 on empty uuid, 404 on unknown uuid."""
    update_q, worker_pool, qmeta = _quiesce(live_server)

    synth = "dddddddd-dddd-dddd-dddd-dddddddddddd"
    assert worker_pool.claim_uuid_for_processing(synth, worker_id=999) is True

    # Happy path
    res = client.post(
        url_for("ui.ui_queue.queue_cancel_running"),
        data={"uuid": synth, "csrf_token": "test"},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    assert body["cancelled"] is True
    assert body["worker_id"] == 999

    # No longer in running per the snapshot
    snap = client.get(url_for("ui.ui_queue.queue_json")).get_json()
    assert all(r["uuid"] != synth for r in snap["running"])

    # Empty uuid → 400
    res = client.post(url_for("ui.ui_queue.queue_cancel_running"), data={"uuid": ""})
    assert res.status_code == 400

    # Unknown uuid → 404
    res = client.post(url_for("ui.ui_queue.queue_cancel_running"), data={"uuid": "never-claimed-anywhere"})
    assert res.status_code == 404

    # cancel_running_uuid() spawned a replacement worker via the route (update_q
    # etc. were available). Tear it down so the next test starts at workers=0.
    live_server.app.set_workers(0)
