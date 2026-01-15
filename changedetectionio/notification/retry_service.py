"""
Notification Retry Service - Centralized retry logic for failed notifications.

Handles:
- Manual immediate retry ("Send Now" button)
- Failed notification retry from dead letter queue
- Batch retry of all failed notifications
- Config reload with cascading priority
"""

from loguru import logger
from changedetectionio.notification_service import NotificationContextData, _check_cascading_vars


class NotificationRetryService:
    """
    Service for retrying failed and scheduled notifications.

    Encapsulates all retry logic including config reloading, task revocation,
    and re-queueing with proper cleanup.
    """

    def __init__(self, huey, datastore):
        """
        Initialize retry service.

        Args:
            huey: Huey instance for task management
            datastore: ChangeDetectionStore instance for watch lookups
        """
        self.huey = huey
        self.datastore = datastore

    def retry_now(self, task_id):
        """
        Manually retry a scheduled/retrying notification immediately.

        Used by "Send Now" button in UI. Revokes the scheduled task and executes
        the notification synchronously in the current thread.

        Args:
            task_id: Huey task ID to retry immediately

        Returns:
            bool: True if successfully executed, False otherwise
        """
        if self.huey is None:
            logger.error("Huey not initialized")
            return False

        try:
            # Find the scheduled task
            notification_data = self._find_scheduled_task(task_id)
            if not notification_data:
                logger.error(f"Task {task_id} not found in schedule")
                return False

            # Revoke scheduled task FIRST to prevent race condition
            self.huey.revoke_by_id(task_id, revoke_once=True)
            logger.info(f"Revoked scheduled task {task_id} before execution")

            # Execute notification synchronously in current thread
            success = self._execute_notification_sync(notification_data, task_id)

            if success:
                # Clean up old metadata and result
                from changedetectionio.notification.task_queue import _delete_result, _delete_task_metadata
                _delete_result(task_id)
                _delete_task_metadata(task_id)
                logger.info(f"✓ Notification sent successfully for task {task_id}")
                return True
            else:
                # Re-queue for automatic retry if manual send failed
                self._requeue_for_retry(notification_data)
                return False

        except Exception as e:
            logger.error(f"Error executing scheduled notification {task_id}: {e}")
            return False

    def retry_failed(self, task_id):
        """
        Retry a failed notification from dead letter queue.

        Removes the task from dead letter queue and re-queues it.
        If it fails again, it will go back to the dead letter queue.

        Args:
            task_id: Huey task ID to retry

        Returns:
            bool: True if successfully queued for retry, False otherwise
        """
        if self.huey is None:
            logger.error("Huey not initialized")
            return False

        try:
            # Get task metadata from storage
            from changedetectionio.notification.task_queue import _get_task_metadata, _delete_result, _delete_task_metadata, queue_notification

            task_metadata = _get_task_metadata(task_id)
            if not task_metadata:
                logger.error(f"Task metadata for {task_id} not found")
                return False

            # Extract notification data
            notification_data = task_metadata.get('notification_data', {})
            if not notification_data:
                logger.error(f"No notification data found for task {task_id}")
                return False

            # Re-queue with current settings
            queue_notification(notification_data)

            # Remove from dead letter queue
            _delete_result(task_id)
            _delete_task_metadata(task_id)

            logger.info(f"Re-queued failed notification task {task_id}")
            return True

        except Exception as e:
            logger.error(f"Error retrying notification {task_id}: {e}")
            return False

    def retry_all_failed(self):
        """
        Retry all failed notifications in the dead letter queue.

        Returns:
            dict: {
                'success': int,  # Number successfully re-queued
                'failed': int,   # Number that failed to re-queue
                'total': int     # Total processed
            }
        """
        if self.huey is None:
            return {'success': 0, 'failed': 0, 'total': 0}

        success_count = 0
        failed_count = 0

        try:
            from huey.utils import Error as HueyError
            from changedetectionio.notification.task_queue import _enumerate_results

            # Get all failed tasks from result store
            results = _enumerate_results()

            for task_id, result in results.items():
                if isinstance(result, (Exception, HueyError)):
                    # Try to retry this failed notification
                    if self.retry_failed(task_id):
                        success_count += 1
                    else:
                        failed_count += 1

            total = success_count + failed_count
            logger.info(f"Retry all: {success_count} succeeded, {failed_count} failed, {total} total")

            return {
                'success': success_count,
                'failed': failed_count,
                'total': total
            }

        except Exception as e:
            logger.error(f"Error retrying all failed notifications: {e}")
            return {
                'success': success_count,
                'failed': failed_count,
                'total': success_count + failed_count
            }

    def reload_notification_config(self, n_object, watch):
        """
        Reload notification_urls and notification_format with cascading priority.

        Priority: Watch settings > Tag settings > Global settings

        This is done on every send/retry to allow operators to fix broken
        notification settings and retry with corrected configuration.

        Args:
            n_object: NotificationContextData object to update
            watch: Watch object
            datastore: Datastore instance

        Raises:
            Exception: If no notification_urls defined after cascading check
        """
        n_object['notification_urls'] = _check_cascading_vars(self.datastore, 'notification_urls', watch)
        n_object['notification_format'] = _check_cascading_vars(self.datastore, 'notification_format', watch)

        if not n_object.get('notification_urls'):
            raise Exception("No notification_urls defined after checking cascading (Watch > Tag > System)")

    # Private helper methods

    def _find_scheduled_task(self, task_id):
        """
        Find a scheduled task by ID and return its notification data.

        Args:
            task_id: Task ID to find

        Returns:
            dict: Notification data or None if not found
        """
        from changedetectionio.notification.message_unpacker import HueyMessageUnpacker

        try:
            scheduled_items = list(self.huey.storage.scheduled_items())

            for scheduled_bytes in scheduled_items:
                result = HueyMessageUnpacker.unpack_scheduled_notification(scheduled_bytes, self.huey)
                if result is None:
                    continue

                found_task_id, notification_data, _ = result
                if found_task_id == task_id:
                    return notification_data

        except Exception as e:
            logger.debug(f"Error finding scheduled task: {e}")

        return None

    def _execute_notification_sync(self, notification_data, task_id):
        """
        Execute notification synchronously in current thread.

        Args:
            notification_data: Notification data dict
            task_id: Task ID for logging

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            from changedetectionio.notification.handler import process_notification

            # Wrap in NotificationContextData if needed
            if not isinstance(notification_data, NotificationContextData):
                notification_data = NotificationContextData(notification_data)

            # Execute synchronously (not via Huey queue)
            logger.info(f"Executing notification for task {task_id} immediately...")
            process_notification(notification_data, self.datastore)

            return True

        except Exception as e:
            logger.warning(f"Failed to send notification for task {task_id}: {e}")
            return False

    def _requeue_for_retry(self, notification_data):
        """
        Re-queue a notification for automatic retry after manual send failed.

        Args:
            notification_data: Notification data to re-queue
        """
        try:
            from changedetectionio.notification.task_queue import send_notification_task

            logger.info("Re-queueing notification for automatic retry after manual send failed")
            send_notification_task(notification_data)
            logger.info("Re-queued notification successfully")

        except Exception as e:
            logger.error(f"Failed to re-queue notification: {e}")
