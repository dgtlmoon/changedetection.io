#!/usr/bin/env python3

from flask import url_for


def test_toggle_returns_to_the_toggled_row(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config.get('DATASTORE')
    uuid = datastore.add_watch(url='https://example.com/toggle-anchor')

    # Without JavaScript (or without a Socket.IO connection) the pause and mute buttons
    # submit the form, so the redirect must bring the browser back to the same row
    for op, attribute in (('pause', 'paused'), ('mute', 'notification_muted')):
        res = client.post(url_for('watchlist.toggle', op=op, uuid=uuid))
        assert res.status_code == 302
        assert res.headers['Location'].endswith(f'#{uuid}')
        assert datastore.data['watching'][uuid].get(attribute) is True

    # The row exists with that id, so the anchor has something to scroll to
    res = client.get(url_for('watchlist.index'))
    assert f'id="{uuid}"'.encode() in res.data


def test_toggle_unknown_watch_has_no_anchor(client, live_server, measure_memory_usage, datastore_path):
    res = client.post(url_for('watchlist.toggle', op='pause', uuid='does-not-exist'))
    assert res.status_code == 302
    assert '#' not in res.headers['Location']
