"""
Unit test for send_step_failure_notification regression.

Before the fix, line 499 called self._check_cascading_vars('notification_format', watch)
which raises AttributeError because _check_cascading_vars is a module-level function,
not a method of NotificationService.
"""

import queue
from unittest.mock import MagicMock


def _make_datastore(watch_uuid, notification_url):
    """Minimal datastore mock that NotificationService and _check_cascading_vars need."""
    watch = MagicMock()
    watch.get = lambda key, default=None: {
        'uuid': watch_uuid,
        'url': 'https://example.com',
        'notification_urls': [notification_url],
        'notification_format': '',
        'notification_muted': False,
    }.get(key, default)
    watch.__getitem__ = lambda self, key: watch.get(key)

    datastore = MagicMock()
    datastore.data = {
        'watching': {watch_uuid: watch},
        'settings': {
            'application': {
                'notification_urls': [],
                'notification_format': 'text',
                'filter_failure_notification_threshold_attempts': 3,
            }
        }
    }
    datastore.get_all_tags_for_watch.return_value = {}
    return datastore, watch


def test_send_step_failure_notification_does_not_raise():
    """send_step_failure_notification must not raise AttributeError (wrong self. prefix on module-level function)."""
    from changedetectionio.notification_service import NotificationService

    watch_uuid = 'test-uuid-1234'
    notification_q = queue.Queue()
    datastore, _ = _make_datastore(watch_uuid, 'post://localhost/test')
    service = NotificationService(datastore=datastore, notification_q=notification_q)

    # Before the fix this raised:
    # AttributeError: 'NotificationService' object has no attribute '_check_cascading_vars'
    service.send_step_failure_notification(watch_uuid=watch_uuid, step_n=0)


def test_send_step_failure_notification_queues_item():
    """A notification object should be placed on the queue when URLs are configured."""
    from changedetectionio.notification_service import NotificationService

    watch_uuid = 'test-uuid-5678'
    notification_q = queue.Queue()
    datastore, _ = _make_datastore(watch_uuid, 'post://localhost/test')
    service = NotificationService(datastore=datastore, notification_q=notification_q)

    service.send_step_failure_notification(watch_uuid=watch_uuid, step_n=1)

    assert not notification_q.empty(), "Expected a notification to be queued"
    item = notification_q.get_nowait()
    assert 'notification_title' in item
    assert 'position 2' in item['notification_title']
