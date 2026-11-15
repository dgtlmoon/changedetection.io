#!/usr/bin/env python3
"""GET /api/v1/changes - every change across a group of watches between two dates, as unified diffs."""
from flask import url_for

from changedetectionio.changes_report import parse_timestamp
from .util import delete_all_watches

T0 = 1700000000  # 2023-11-14T22:13:20Z


def _setup(client):
    datastore = client.application.config['DATASTORE']
    group = datastore.add_tag('competitors')

    def watch(url, title, snapshots, tags=True):
        uuid = datastore.add_watch(url=url, extras={'title': title, 'paused': True,
                                                    'tags': [group] if tags else []})
        w = datastore.data['watching'][uuid]
        for i, (ts, text) in enumerate(snapshots):
            w.save_history_blob(text, ts, f'snap{i}')
        return uuid

    uuids = {
        # Plain text change inside the range
        'policy': watch('https://example.com/privacy', 'Privacy Policy', [
            (T0, 'Intro\nWe may share data with\nour payment processor.\nOutro'),
            (T0 + 100, 'Intro\nWe may share data with\nour payment processor and advertising partners.\nOutro'),
        ]),
        # Changed and changed back: two changes, no net difference
        'price': watch('https://example.com/blender', 'Pro Blender', [
            (T0, 'In stock, 149.99 USD'),
            (T0 + 50, 'In stock, 129.99 USD'),
            (T0 + 150, 'In stock, 149.99 USD'),
        ]),
        # Nothing inside the range
        'quiet': watch('https://example.com/quiet', 'Quiet page', [
            (T0 - 100, 'Same'),
            (T0, 'Same, edited before the range'),
        ]),
        # First seen inside the range, not in the group
        'new': watch('https://example.com/new', 'New page', [
            (T0 + 120, 'Hello'),
            (T0 + 130, 'Hello world'),
        ], tags=False),
    }
    return datastore, group, uuids


def _get(client, api_key, **params):
    return client.get(url_for('changes'), query_string=params, headers={'x-api-key': api_key})


def test_api_changes(client, live_server, measure_memory_usage, datastore_path):
    datastore, group, uuids = _setup(client)
    api_key = datastore.data['settings']['application'].get('api_access_token')
    window = {'from': T0, 'to': T0 + 200}

    # Unified diff for the group, net change
    res = _get(client, api_key, tag=group, **window)
    assert res.status_code == 200
    assert res.mimetype == 'text/plain'
    text = res.get_data(as_text=True)
    assert text.startswith('# 2 of 3 monitors changed (3 changes)')
    assert '### Privacy Policy - https://example.com/privacy' in text
    assert f"uuid: {uuids['policy']} | 2023-11-14T22:13:20Z -> 2023-11-14T22:15:00Z | 1 change" in text
    assert '-our payment processor.\n+our payment processor and advertising partners.' in text
    # context=1: the line next to the change is there, the one two lines away isn't
    assert ' We may share data with' in text and ' Intro' not in text
    # Changed and back again: listed, but no diff under it
    assert '### Pro Blender - https://example.com/blender' in text
    assert '| 2 changes, no net difference' in text
    assert '149.99' not in text
    # Unchanged and ungrouped watches are left out
    assert 'Quiet page' not in text and 'New page' not in text
    # Most recently changed first
    assert text.index('Pro Blender') < text.index('Privacy Policy')

    # mode=each shows the price going down and back up
    res = _get(client, api_key, tag=group, mode='each', format='json', **window)
    assert res.status_code == 200
    price = next(w for w in res.json['watches'] if w['uuid'] == uuids['price'])
    assert price['diff'].count('@@') == 4  # two hunks, an opening and closing @@ each
    assert '-In stock, 149.99 USD\n+In stock, 129.99 USD' in price['diff']
    assert '-In stock, 129.99 USD\n+In stock, 149.99 USD' in price['diff']
    assert res.json['total'] == 2 and res.json['monitors_checked'] == 3 and res.json['changes_total'] == 3

    # The group by name works too, and without a group every watch is looked at
    res = _get(client, api_key, tag='Competitors', format='json', **window)
    assert {w['uuid'] for w in res.json['watches']} == {uuids['policy'], uuids['price']}
    res = _get(client, api_key, format='json', **window)
    new = next(w for w in res.json['watches'] if w['uuid'] == uuids['new'])
    assert new['new_in_period'] and new['changes'] == 1
    assert '-Hello\n+Hello world' in new['diff']
    assert 'new in period' in _get(client, api_key, **window).get_data(as_text=True)

    # An explicit list of watches
    res = _get(client, api_key, uuids=f"{uuids['policy']},{uuids['quiet']}", format='json', **window)
    assert [w['uuid'] for w in res.json['watches']] == [uuids['policy']]

    # Paging, most recently changed first
    res = _get(client, api_key, tag=group, format='json', limit=1, offset=1, **window)
    assert [w['uuid'] for w in res.json['watches']] == [uuids['policy']] and res.json['total'] == 2

    # Long diffs are cut, pointing at the full per-watch diff
    res = _get(client, api_key, tag=group, max_lines_per_watch=3, format='json', **window)
    policy = next(w for w in res.json['watches'] if w['uuid'] == uuids['policy'])
    assert policy['truncated']
    assert f"/api/v1/watch/{uuids['policy']}/difference/{T0}/{T0 + 100}" in policy['diff']

    # ISO dates work as well as unix seconds
    res = _get(client, api_key, tag=group, format='json', **{'from': '2023-11-14T22:13:20Z', 'to': '2023-11-15'})
    assert res.json['total'] == 2

    # Input errors
    assert _get(client, api_key, tag=group).status_code == 400  # no from
    assert _get(client, api_key, mode='nope', **window).status_code == 400
    assert _get(client, api_key, format='html', **window).status_code == 400
    assert _get(client, api_key, **{'from': T0, 'to': T0 - 1}).status_code == 400
    assert _get(client, api_key, context=99, **window).status_code == 400
    assert _get(client, api_key, tag='no-such-group', **window).status_code == 404
    assert _get(client, api_key, uuids='no-such-watch', **window).status_code == 404
    # The API key is required
    assert client.get(url_for('changes'), query_string=window).status_code == 403

    client.post(url_for('tags.delete_all'), follow_redirects=True)
    delete_all_watches(client)


def test_parse_timestamp():
    assert parse_timestamp('1700000000') == 1700000000
    assert parse_timestamp(1700000000) == 1700000000
    assert parse_timestamp('2023-11-14T22:13:20Z') == 1700000000
    assert parse_timestamp('2023-11-14T23:13:20+01:00') == 1700000000
    assert parse_timestamp('2023-11-15') == 1700006400
    assert parse_timestamp('') is None
    assert parse_timestamp('next tuesday') is None
