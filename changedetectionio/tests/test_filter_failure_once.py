"""A missing selector is one incident until an actual successful filter check."""
import json
import os

import pytest
from flask import url_for

from .util import wait_for_all_checks, wait_for_notification_endpoint_output, write_test_file_and_sync


def _page(datastore_path, present, marker=''):
    content = '<html><body><div id="tracked">$24.00</div></body></html>' if present else f'<html><body>Unavailable {marker}</body></html>'
    write_test_file_and_sync(os.path.join(datastore_path, 'endpoint-content.txt'), content)


def _check(client, uuid):
    client.post(url_for('ui.form_watch_checknow', uuid=uuid), follow_redirects=True)
    assert wait_for_all_checks(client)


def _watch(client, datastore_path, monkeypatch, *, once=True, threshold=2, processor='text_json_diff'):
    from changedetectionio.flask_app import notification_q

    datastore = client.application.config['DATASTORE']
    datastore.data['settings']['application']['filter_failure_notification_threshold_attempts'] = threshold
    queued = []
    original_put = notification_q.put

    def record_put(item, *args, **kwargs):
        result = original_put(item, *args, **kwargs)
        if result is not False and 'CSS/xPath filter was not present' in item.get('notification_title', ''):
            queued.append(item)
        return result

    monkeypatch.setattr(notification_q, 'put', record_put)
    _page(datastore_path, present=True)
    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True), extras={
        'fetch_backend': 'html_requests',
        'processor': processor,
        'include_filters': ['#tracked'],
        'filter_failure_notification_send': True,
        'filter_failure_notification_once': once,
        'notification_urls': [url_for('test_notification_endpoint', _external=True).replace('http', 'post')],
        'time_between_check_use_default': False,
        'time_between_check': {'hours': 24},
    })
    assert wait_for_all_checks(client)
    assert datastore.data['watching'][uuid]['consecutive_filter_failures'] == 0
    return datastore, uuid, queued


@pytest.mark.parametrize('threshold', [0, 1, 2])
@pytest.mark.parametrize('processor', ['text_json_diff', 'restock_diff'])
def test_missing_filter_alerts_once_then_rearms_after_matching_content(client, live_server, datastore_path, monkeypatch, threshold, processor):
    datastore, uuid, queued = _watch(client, datastore_path, monkeypatch, threshold=threshold, processor=processor)
    _page(datastore_path, present=False)
    for attempt in range(max(1, threshold) * 3):
        # Real shops can change unrelated page content while the selected product stays absent.
        _page(datastore_path, present=False, marker=str(attempt))
        _check(client, uuid)
    assert len(queued) == 1
    assert datastore.data['watching'][uuid].get('filter_failure_notification_sent') is True
    assert wait_for_notification_endpoint_output(datastore_path)
    with open(os.path.join(datastore_path, 'notification.txt')) as f:
        assert 'CSS/xPath filters' in f.read()

    _page(datastore_path, present=True)
    _check(client, uuid)
    assert datastore.data['watching'][uuid]['filter_failure_notification_sent'] is False
    assert datastore.data['watching'][uuid]['consecutive_filter_failures'] == 0
    _page(datastore_path, present=False)
    for _ in range(max(1, threshold)):
        _check(client, uuid)
    assert len(queued) == 2


@pytest.mark.parametrize('processor', ['text_json_diff', 'restock_diff'])
def test_repeating_filter_alert_mode_retains_threshold_cadence(client, live_server, datastore_path, monkeypatch, processor):
    datastore, uuid, queued = _watch(client, datastore_path, monkeypatch, once=False, processor=processor)
    _page(datastore_path, present=False)
    for _ in range(4):
        _check(client, uuid)
    assert len(queued) == 2
    assert datastore.data['watching'][uuid]['consecutive_filter_failures'] == 0


@pytest.mark.parametrize('processor', ['text_json_diff', 'restock_diff'])
def test_unchanged_missing_document_does_not_count_as_filter_recovery(client, live_server, datastore_path, monkeypatch, processor):
    datastore, uuid, queued = _watch(client, datastore_path, monkeypatch, threshold=1, processor=processor)
    _page(datastore_path, present=False)
    _check(client, uuid)
    assert len(queued) == 1
    _check(client, uuid)
    assert 'no filters were found' in (datastore.data['watching'][uuid]['last_error'] or '')
    assert len(queued) == 1


@pytest.mark.parametrize('blocked_by', ['watch_mute', 'all_mute', 'no_urls', 'queue_rejects', 'queue_raises'])
def test_unsent_filter_alert_does_not_consume_incident(client, live_server, datastore_path, monkeypatch, blocked_by):
    from changedetectionio.flask_app import notification_q

    datastore, uuid, queued = _watch(client, datastore_path, monkeypatch, threshold=1)
    watch = datastore.data['watching'][uuid]
    notification_urls = watch['notification_urls']
    real_put = notification_q.put
    if blocked_by == 'watch_mute':
        watch['notification_muted'] = True
    elif blocked_by == 'all_mute':
        datastore.data['settings']['application']['all_muted'] = True
    elif blocked_by == 'no_urls':
        watch['notification_urls'] = []
    elif blocked_by == 'queue_rejects':
        monkeypatch.setattr(notification_q, 'put', lambda *a, **kw: False)
    else:
        def fail_put(*a, **kw):
            raise RuntimeError('test queue unavailable')
        monkeypatch.setattr(notification_q, 'put', fail_put)

    _page(datastore_path, present=False)
    _check(client, uuid)
    assert not queued
    assert watch.get('filter_failure_notification_sent', False) is False

    watch['notification_muted'] = False
    datastore.data['settings']['application']['all_muted'] = False
    watch['notification_urls'] = notification_urls
    monkeypatch.setattr(notification_q, 'put', real_put)
    _check(client, uuid)
    assert len(queued) == 1
    assert watch['filter_failure_notification_sent'] is True


def test_filter_alert_state_survives_reload_and_is_readonly_in_api(client, live_server, datastore_path, monkeypatch):
    from changedetectionio.model.Watch import model as Watch

    datastore, uuid, queued = _watch(client, datastore_path, monkeypatch, threshold=1)
    _page(datastore_path, present=False)
    _check(client, uuid)
    assert len(queued) == 1
    watch = datastore.data['watching'][uuid]
    watch.commit()
    with open(os.path.join(watch.data_dir, 'watch.json')) as f:
        saved = json.load(f)
    restored = Watch(datastore_path=datastore_path, default=saved, __datastore=datastore)
    assert restored['filter_failure_notification_sent'] is True
    restored.reset_watch_edited_flag()
    restored['filter_failure_notification_sent'] = True
    assert restored.was_edited is False
    datastore.data['watching'][uuid] = restored
    _check(client, uuid)
    assert len(queued) == 1

    api_key = datastore.data['settings']['application']['api_access_token']
    headers = {'x-api-key': api_key}
    response = client.get(url_for('watch', uuid=uuid), headers=headers)
    assert response.status_code == 200
    payload = response.json
    assert payload['filter_failure_notification_once'] is True
    payload['filter_failure_notification_once'] = False
    payload['filter_failure_notification_sent'] = False
    response = client.put(url_for('watch', uuid=uuid), json=payload, headers=headers)
    assert response.status_code == 200
    assert restored['filter_failure_notification_once'] is False
    assert restored['filter_failure_notification_sent'] is True


def test_filter_alert_once_option_is_saved_by_edit_form(client, live_server, datastore_path, monkeypatch):
    datastore, uuid, _ = _watch(client, datastore_path, monkeypatch)
    response = client.get(url_for('ui.ui_edit.edit_page', uuid=uuid))
    assert b'name="filter_failure_notification_once"' in response.data
    data = {
        'url': datastore.data['watching'][uuid]['url'],
        'fetch_backend': 'html_requests',
        'filter_failure_notification_send': 'y',
        'filter_failure_notification_once': 'y',
        'time_between_check_use_default': 'y',
    }
    response = client.post(url_for('ui.ui_edit.edit_page', uuid=uuid), data=data, follow_redirects=True)
    assert b'Updated watch.' in response.data
    assert datastore.data['watching'][uuid]['filter_failure_notification_once'] is True
    data.pop('filter_failure_notification_once')
    response = client.post(url_for('ui.ui_edit.edit_page', uuid=uuid), data=data, follow_redirects=True)
    assert b'Updated watch.' in response.data
    assert datastore.data['watching'][uuid]['filter_failure_notification_once'] is False


def test_browser_step_errors_do_not_consume_filter_failure_threshold(client, live_server, datastore_path, monkeypatch):
    from changedetectionio.content_fetchers.exceptions import BrowserStepsStepException
    from changedetectionio.processors.text_json_diff.processor import perform_site_check
    from playwright._impl._errors import TimeoutError

    datastore, uuid, queued = _watch(client, datastore_path, monkeypatch)
    _page(datastore_path, present=False)
    _check(client, uuid)
    watch = datastore.data['watching'][uuid]
    assert watch['consecutive_filter_failures'] == 1
    run_changedetection = perform_site_check.run_changedetection

    def step_failure(*args, **kwargs):
        raise BrowserStepsStepException(1, TimeoutError('test missing step'))

    monkeypatch.setattr(perform_site_check, 'run_changedetection', step_failure)
    for _ in range(2):
        _check(client, uuid)
    assert watch['consecutive_filter_failures'] == 1
    assert not watch.get('filter_failure_notification_sent', False)
    assert not queued

    monkeypatch.setattr(perform_site_check, 'run_changedetection', run_changedetection)
    _check(client, uuid)
    assert len(queued) == 1
    assert watch['filter_failure_notification_sent'] is True
    # A later browser-step error does not end the still-missing filter incident.
    monkeypatch.setattr(perform_site_check, 'run_changedetection', step_failure)
    _check(client, uuid)
    monkeypatch.setattr(perform_site_check, 'run_changedetection', run_changedetection)
    _check(client, uuid)
    assert len(queued) == 1


def test_new_and_legacy_monitors_default_to_single_filter_alert(client, live_server, datastore_path):
    from changedetectionio.model.Watch import model as Watch

    datastore = client.application.config['DATASTORE']
    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True), extras={'paused': True})
    watch = datastore.data['watching'][uuid]
    assert watch['filter_failure_notification_once'] is True
    assert watch['filter_failure_notification_sent'] is False
    restored = Watch(datastore_path=datastore_path, default={
        'uuid': uuid, 'url': watch['url'], 'consecutive_filter_failures': 3,
    }, __datastore=datastore)
    assert restored['filter_failure_notification_once'] is True
    assert restored['filter_failure_notification_sent'] is False
