#!/usr/bin/env python3
"""What muting a group does. See notification_service.notifications_muted()."""
import queue

import pytest
from flask import url_for

from changedetectionio.notification_service import NotificationService, notification_senders, notifications_muted
from .util import delete_all_watches


@pytest.fixture
def setup(client, live_server, datastore_path):
    datastore = client.application.config.get('DATASTORE')
    app = datastore.data['settings']['application']
    app['notification_urls'] = []
    app['notification_format'] = 'text'
    yield datastore
    app['notification_urls'] = []
    app['tags'].clear()
    delete_all_watches(client)


def _group(datastore, title, **settings):
    uuid = datastore.add_tag(title=title)
    datastore.data['settings']['application']['tags'][uuid].update(settings)
    return uuid


def _watch(datastore, tags=(), **settings):
    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True),
                               extras={'paused': True, 'include_filters': ['#gone'], **settings})
    datastore.data['watching'][uuid]['tags'] = list(tags)
    return uuid


def _error_alerts(datastore, uuid, step=False):
    """The URLs of every alert queued for this watch's error"""
    q = queue.Queue()
    service = NotificationService(datastore=datastore, notification_q=q)
    if step:
        service.send_step_failure_notification(watch_uuid=uuid, step_n=1)
    else:
        service.send_filter_failure_notification(watch_uuid=uuid)
    alerts = []
    while not q.empty():
        alerts.append(q.get()['notification_urls'])
    return alerts


def test_a_muted_group_mutes_its_watches(client, live_server, measure_memory_usage, datastore_path, setup):
    datastore = setup
    app = datastore.data['settings']['application']
    app['notification_urls'] = ['json://system']

    # A group with no notification settings of its own at all, and one of each kind that has
    plain = _group(datastore, 'Plain')
    groups = {
        'plain': plain,
        'fallback': _group(datastore, 'Fallback', notification_group_mode='fallback', notification_urls=['json://group']),
        'add': _group(datastore, 'Add', notification_group_mode='add', notification_urls=['json://group']),
        'replace': _group(datastore, 'Replace', notification_group_mode='replace', notification_urls=['json://group']),
    }
    other = _group(datastore, 'Another group, not muted', notification_group_mode='add', notification_urls=['json://other'])

    for kind, group_uuid in groups.items():
        group = app['tags'][group_uuid]
        for own_urls in ([], ['json://watch']):
            uuid = _watch(datastore, tags=[group_uuid, other], notification_urls=own_urls)
            watch = datastore.data['watching'][uuid]
            assert notification_senders(datastore, watch), kind
            assert not notifications_muted(datastore, watch)

            group['notification_muted'] = True
            assert notifications_muted(datastore, watch), kind
            assert notification_senders(datastore, watch) == [], f"{kind}: nothing of the watch, its other group or the system"
            assert _error_alerts(datastore, uuid) == [] and _error_alerts(datastore, uuid, step=True) == [], kind
            assert not watch.get('notification_muted'), "The watch's own setting is left alone"

            group['notification_muted'] = False
            assert notification_senders(datastore, watch), kind

    # A watch that is not in the muted group goes on as it was
    app['tags'][plain]['notification_muted'] = True
    outside = _watch(datastore, notification_urls=['json://watch'])
    assert [s['notification_urls'] for s in notification_senders(datastore, datastore.data['watching'][outside])] == [['json://watch']]

    # A group that applies by URL pattern mutes the watches it matches
    by_url = _group(datastore, 'By URL', url_match_pattern='*/test-endpoint*', notification_muted=True)
    assert notification_senders(datastore, datastore.data['watching'][outside]) == []
    app['tags'][by_url]['notification_muted'] = False
    assert notification_senders(datastore, datastore.data['watching'][outside])
