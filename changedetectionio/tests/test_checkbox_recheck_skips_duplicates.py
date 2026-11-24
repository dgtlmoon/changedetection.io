#!/usr/bin/env python3
"""Recheck on a selection queues each watch once: not twice when selected twice, and not while it is
already queued or being checked."""

from flask import url_for

from .util import wait_for_all_checks


def test_checkbox_recheck_skips_duplicates(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    datastore = client.application.config.get('DATASTORE')
    test_url = url_for('test_endpoint', _external=True)
    uuids = [datastore.add_watch(url=test_url) for _ in range(3)]
    wait_for_all_checks(client)
    checked_before = {u: datastore.data['watching'][u]['last_checked'] for u in uuids}

    # The same watch ticked twice and one that does not exist are not counted
    res = client.post(
        url_for("ui.form_watch_list_checkbox_operations"),
        data={"op": "recheck", "uuids": uuids + [uuids[0], "not-a-watch"]},
        follow_redirects=True,
    )
    assert b"3 watches queued for rechecking" in res.data

    wait_for_all_checks(client)
    for u in uuids:
        assert datastore.data['watching'][u]['last_checked'] >= checked_before[u]

    # One that is being checked right now is left alone
    from changedetectionio import worker_pool
    monkeypatch.setattr(worker_pool, 'get_running_uuids', lambda: [uuids[0]])
    res = client.post(
        url_for("ui.form_watch_list_checkbox_operations"),
        data={"op": "recheck", "uuids": uuids},
        follow_redirects=True,
    )
    assert b"2 watches queued for rechecking" in res.data
    monkeypatch.undo()
    wait_for_all_checks(client)
