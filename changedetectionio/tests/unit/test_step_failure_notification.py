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
    # step_n is already 1-based (base.py increments step_n before running each step, so the
    # first browser step raises with step_n=1), so the reported position must equal step_n.
    assert 'position 1' in item['notification_title']


def test_send_step_failure_notification_position_matches_step_number():
    """Regression for #4200: the reported browser-step position must equal the 1-based
    step_n, not step_n + 1. step_n arrives already 1-based (BrowserStepsStepException is
    raised with the post-increment counter, and worker.py passes e.step_n through), and the
    frontend highlights nth-child(browser_steps_last_error_step) / compares === i+1, both
    1-based. An extra +1 mis-numbers the notification and highlights the wrong step."""
    from changedetectionio.notification_service import NotificationService

    for step_n in (1, 2, 5):
        watch_uuid = f'test-uuid-pos-{step_n}'
        notification_q = queue.Queue()
        datastore, _ = _make_datastore(watch_uuid, 'post://localhost/test')
        service = NotificationService(datastore=datastore, notification_q=notification_q)

        service.send_step_failure_notification(watch_uuid=watch_uuid, step_n=step_n)

        item = notification_q.get_nowait()
        assert f'position {step_n} could not be run' in item['notification_title']
        assert f'position {step_n + 1}' not in item['notification_title']
        assert f'position {step_n} for the web page watch' in item['notification_body']
