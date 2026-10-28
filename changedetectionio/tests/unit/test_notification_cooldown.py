import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest


class _Watch(dict):
    history = {'1000': 'previous snapshot', '2000': 'current snapshot'}

    def get_history_snapshot(self, timestamp):
        return self.history[timestamp]


def _make_service(cooldown_hours=0):
    from changedetectionio.notification_service import NotificationService

    watch = _Watch({
        'uuid': 'test-watch',
        'url': 'https://example.com',
        'notification_urls': ['json://localhost/'],
        'notification_title': 'Title',
        'notification_body': 'Body',
        'notification_format': 'text',
        'notification_muted': False,
        'notification_cooldown_hours': cooldown_hours,
        'last_content_notification_at': 0,
        'notification_alert_count': 0,
    })
    datastore = SimpleNamespace(
        data={
            'watching': {'test-watch': watch},
            'settings': {'application': {'notification_urls': [], 'notification_format': 'text'}},
        },
        lock=threading.Lock(),
    )

    def update_watch(uuid, update_obj):
        datastore.data['watching'][uuid].update(update_obj)

    datastore.update_watch = update_watch
    datastore.get_all_tags_for_watch = lambda uuid: {}
    service = NotificationService(datastore, notification_q=object())
    queue_calls = []
    service.queue_notification_for_watch = lambda **kwargs: queue_calls.append(kwargs)
    return service, datastore, queue_calls


def test_disabled_cooldown_preserves_notifications(monkeypatch):
    service, datastore, queue_calls = _make_service()
    monkeypatch.setattr('changedetectionio.notification_service.time.time', lambda: 100_000)

    assert service.send_content_changed_notification('test-watch') is True
    assert service.send_content_changed_notification('test-watch') is True
    assert len(queue_calls) == 2
    assert datastore.data['watching']['test-watch']['notification_alert_count'] == 2


def test_cooldown_suppresses_changes_until_interval_expires(monkeypatch):
    service, datastore, queue_calls = _make_service(cooldown_hours=1)
    now = [100_000]
    monkeypatch.setattr('changedetectionio.notification_service.time.time', lambda: now[0])

    assert service.send_content_changed_notification('test-watch') is True
    assert datastore.data['watching']['test-watch']['last_content_notification_at'] == now[0]

    now[0] += 3599
    assert service.send_content_changed_notification('test-watch') is False
    assert len(queue_calls) == 1

    now[0] += 1
    assert service.send_content_changed_notification('test-watch') is True
    assert len(queue_calls) == 2


def test_queue_failure_does_not_start_cooldown(monkeypatch):
    service, datastore, _ = _make_service(cooldown_hours=1)
    monkeypatch.setattr('changedetectionio.notification_service.time.time', lambda: 100_000)

    def fail_to_queue(**kwargs):
        raise RuntimeError('queue unavailable')

    service.queue_notification_for_watch = fail_to_queue

    with pytest.raises(RuntimeError, match='queue unavailable'):
        service.send_content_changed_notification('test-watch')

    watch = datastore.data['watching']['test-watch']
    assert watch['last_content_notification_at'] == 0
    assert watch['notification_alert_count'] == 0


def test_concurrent_changes_only_admit_one_notification_during_cooldown(monkeypatch):
    service, datastore, queue_calls = _make_service(cooldown_hours=24)
    monkeypatch.setattr('changedetectionio.notification_service.time.time', lambda: 100_000)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(
            service.send_content_changed_notification,
            ('test-watch', 'test-watch'),
        ))

    assert sorted(results) == [False, True]
    assert len(queue_calls) == 1
    assert datastore.data['watching']['test-watch']['notification_alert_count'] == 1


def test_cooldown_is_included_in_notification_eligibility(monkeypatch):
    from changedetectionio.notification_service import watch_will_send_content_changed_notification

    service, datastore, _ = _make_service(cooldown_hours=24)
    watch = datastore.data['watching']['test-watch']
    watch['last_content_notification_at'] = 90_000
    monkeypatch.setattr('changedetectionio.notification_service.time.time', lambda: 100_000)

    assert watch_will_send_content_changed_notification(datastore, watch) is False


@pytest.mark.parametrize('invalid_value', (-1, '24', 1.5, True))
def test_invalid_cooldown_value_is_rejected(monkeypatch, invalid_value):
    from changedetectionio.notification_service import NotificationService

    service, datastore, _ = _make_service()
    datastore.data['watching']['test-watch']['notification_cooldown_hours'] = invalid_value
    monkeypatch.setattr('changedetectionio.notification_service.time.time', lambda: 100_000)

    with pytest.raises(ValueError, match='notification_cooldown_hours'):
        service.send_content_changed_notification('test-watch')
