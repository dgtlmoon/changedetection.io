#!/usr/bin/env python3
"""Where error alerts go (a filter that is no longer on the page, a browser step that could not be run).
See notification_service.error_notification_senders()."""
import queue

import pytest
from flask import url_for

from changedetectionio.notification_service import NotificationService, notification_senders
from .util import delete_all_watches


@pytest.fixture
def setup(client, live_server, datastore_path):
    datastore = client.application.config.get('DATASTORE')
    app = datastore.data['settings']['application']
    app['notification_urls'] = []
    app['notification_errors_urls'] = []
    app['notification_format'] = 'text'
    yield datastore
    app['notification_urls'] = []
    app['notification_errors_urls'] = []
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
    """(urls, format) of every alert queued for this watch's error"""
    q = queue.Queue()
    service = NotificationService(datastore=datastore, notification_q=q)
    if step:
        service.send_step_failure_notification(watch_uuid=uuid, step_n=1)
    else:
        service.send_filter_failure_notification(watch_uuid=uuid)
    alerts = []
    while not q.empty():
        n_object = q.get()
        assert n_object['uuid'] == uuid and n_object['watch_url']
        alerts.append((n_object['notification_urls'], n_object['notification_format']))
    return alerts


def test_error_alerts_follow_the_watch_then_its_groups_then_the_system(client, live_server, measure_memory_usage, datastore_path, setup):
    datastore = setup
    app = datastore.data['settings']['application']
    fallback = _group(datastore, 'Fallback', notification_group_mode='fallback', notification_urls=['json://fallback-group'])
    replace = _group(datastore, 'Replace', notification_group_mode='replace', notification_urls=['json://replace-group'], notification_format='html')
    add = _group(datastore, 'Add', notification_group_mode='add', notification_urls=['json://add-group'])
    off = _group(datastore, 'Off', notification_urls=['json://off-group'])

    own = _watch(datastore, notification_urls=['json://watch'])
    by_fallback = _watch(datastore, tags=[fallback])
    by_replace = _watch(datastore, tags=[replace], notification_urls=['json://watch'])
    by_add = _watch(datastore, tags=[add], notification_urls=['json://watch'])
    in_off_group = _watch(datastore, tags=[off])

    for step in (False, True):
        assert _error_alerts(datastore, own, step) == [(['json://watch'], 'text')]
        assert _error_alerts(datastore, by_fallback, step) == [(['json://fallback-group'], 'text')], "None of its own, its group's"
        assert _error_alerts(datastore, by_replace, step) == [(['json://replace-group'], 'html')], "The group's instead of the watch's own"
        assert [urls for urls, _ in _error_alerts(datastore, by_add, step)] == [['json://watch'], ['json://add-group']]
        assert _error_alerts(datastore, in_off_group, step) == [], "Nothing anywhere, nothing sent"

    # Nothing on the watch or a group, the system's
    app['notification_urls'] = ['json://system']
    assert _error_alerts(datastore, in_off_group) == [(['json://system'], 'text')]
    assert _error_alerts(datastore, by_replace) == [(['json://replace-group'], 'html')], "Not the system's, the group stands in for it"


def test_where_to_send_errors_setting(client, live_server, measure_memory_usage, datastore_path, setup):
    datastore = setup
    app = datastore.data['settings']['application']
    group = _group(datastore, 'Shops', notification_group_mode='replace', notification_urls=['json://group'], notification_format='html')
    own = _watch(datastore, notification_urls=['json://watch'])
    in_group = _watch(datastore, tags=[group])
    nothing_set = _watch(datastore)

    # Saved from the notification settings page, with what was there kept
    res = client.get(url_for('settings.notifications.apprise'))
    assert b'name="notification_errors_urls"' in res.data and b'Where to send errors?' in res.data
    # Folded away, with its own "Add a notification service" that adds to this list and not to the main one
    assert b'<details class="form-wrapper" id="notification-errors-urls">' in res.data
    assert b'id="notification-setup-errors" class="notification-setup" data-target="textarea.notification-errors-urls"' in res.data
    assert b'id="notification-setup" class="notification-setup"' in res.data
    assert res.data.count(b'notification-setup.js') == 1, "One script sets up both"
    res = client.post(url_for('settings.notifications.apprise'), data={
        'notification_urls': '',
        'notification_title': 'Title',
        'notification_body': 'Body',
        'notification_format': 'text',
        'base_url': '',
        'notification_errors_urls': 'json://errors-one\r\njson://errors-two',
    }, follow_redirects=True)
    assert b'Settings updated.' in res.data
    assert app['notification_errors_urls'] == ['json://errors-one', 'json://errors-two']
    res = client.get(url_for('settings.notifications.apprise'))
    assert b'json://errors-one' in res.data
    assert b'<details class="form-wrapper" id="notification-errors-urls" open>' in res.data, "Open when it has something"

    # Every error goes there and only there, in the system's format
    for uuid in (own, in_group, nothing_set):
        for step in (False, True):
            assert _error_alerts(datastore, uuid, step) == [(['json://errors-one', 'json://errors-two'], 'text')]

    # A change on the watch is sent where it always was
    assert [s['notification_urls'] for s in notification_senders(datastore, datastore.data['watching'][own])] == [['json://watch']]
    assert [s['notification_urls'] for s in notification_senders(datastore, datastore.data['watching'][in_group])] == [['json://group']]

    # Something that is not a notification URL is refused, what was saved stays
    res = client.post(url_for('settings.notifications.apprise'), data={
        'notification_urls': '', 'notification_title': 'Title', 'notification_body': 'Body',
        'notification_format': 'text', 'base_url': '',
        'notification_errors_urls': 'not-a-notification-url',
    }, follow_redirects=True)
    assert b'Settings updated.' not in res.data
    assert app['notification_errors_urls'] == ['json://errors-one', 'json://errors-two']

    # A muted watch sends none
    datastore.data['watching'][own]['notification_muted'] = True
    assert _error_alerts(datastore, own) == [] and _error_alerts(datastore, own, step=True) == []
    datastore.data['watching'][own]['notification_muted'] = False

    # Emptied again, back to where the watch's notifications go
    app['notification_errors_urls'] = []
    assert _error_alerts(datastore, own) == [(['json://watch'], 'text')]
    assert _error_alerts(datastore, nothing_set) == []
