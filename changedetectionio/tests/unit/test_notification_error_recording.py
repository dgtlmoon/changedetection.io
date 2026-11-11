#!/usr/bin/env python3

"""A notification that cannot even be prepared must show up in the UI.

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_notification_error_recording

#4461 - an invalid notification format raised while the notification object was
being built, which is BEFORE the notification was queued. The notification runner
never saw it, so the watch kept an empty 'last_notification_error' and nothing
was shown in the UI - the error was only in the log.

Errors that happen while the notification is delivered are already caught (and
shown) by the notification runner, this is the gap that was left.
"""

import asyncio
import queue
import unittest
from unittest.mock import MagicMock


def _make_datastore(watch_uuid, notification_format):
    """A datastore mock with one watch that has a broken notification format."""
    watch = MagicMock()
    watch_data = {
        'uuid': watch_uuid,
        'url': 'https://example.com',
        'notification_urls': ['post://localhost/test'],
        'notification_format': notification_format,
        'notification_muted': False,
        'notification_alert_count': 0,
    }
    watch.get = lambda key, default=None: watch_data.get(key, default)
    watch.__getitem__ = lambda self, key: watch.get(key)
    # Two snapshots, so the notification is actually attempted.
    watch.history = {'1700000000': 'before', '1700000060': 'after'}

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


class TestNotificationErrorRecording(unittest.TestCase):

    def test_invalid_notification_format_is_recorded_on_the_watch(self):
        """The regression - the error has to be visible in the UI."""
        from changedetectionio import worker

        watch_uuid = 'test-uuid-invalid-format'
        datastore, _ = _make_datastore(watch_uuid, 'fnoobar')

        asyncio.run(worker.send_content_changed_notification(watch_uuid, queue.Queue(), datastore))

        datastore.update_watch.assert_called_once()
        kwargs = datastore.update_watch.call_args.kwargs
        self.assertEqual(kwargs.get('uuid'), watch_uuid)
        self.assertTrue(
            kwargs.get('update_obj', {}).get('last_notification_error'),
            "The notification error was not recorded on the watch, so nothing shows in the UI"
        )

    def test_a_valid_notification_records_no_error(self):
        """A working notification must not mark the watch as failed."""
        from changedetectionio import worker

        watch_uuid = 'test-uuid-valid-format'
        datastore, _ = _make_datastore(watch_uuid, 'text')

        asyncio.run(worker.send_content_changed_notification(watch_uuid, queue.Queue(), datastore))

        for call in datastore.update_watch.call_args_list:
            update_obj = call.kwargs.get('update_obj') or {}
            self.assertNotIn('last_notification_error', update_obj,
                             "A working notification must not mark the watch as failed")

    def test_the_error_reason_ends_up_in_the_notification_log(self):
        """The link in the UI points at the notification log, so put it there."""
        from changedetectionio import flask_app
        from changedetectionio import worker

        watch_uuid = 'test-uuid-invalid-format-log'
        datastore, _ = _make_datastore(watch_uuid, 'fnoobar')

        before = len(flask_app.notification_debug_log)

        asyncio.run(worker.send_content_changed_notification(watch_uuid, queue.Queue(), datastore))

        added = flask_app.notification_debug_log[before:]
        self.assertTrue(any('fnoobar' in line for line in added),
                        f"The reason was not added to the notification log: {added}")

    def test_a_broken_datastore_does_not_raise(self):
        """Recording the error must never take the worker down."""
        from changedetectionio import worker

        datastore = MagicMock()
        datastore.update_watch.side_effect = Exception("datastore is broken")

        # Must not raise
        worker.record_notification_error(datastore, 'some-uuid', Exception("boom"))


if __name__ == '__main__':
    unittest.main()
