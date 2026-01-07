"""
Notification State Retriever - Centralized logic for retrieving notification state.

Handles:
- Pending/queued notifications (from Huey queue and schedule)
- Failed notifications (from dead letter queue)
- Delivered notifications (from audit trail storage)
- Unified event timeline for UI
- Apprise logs for individual tasks
"""

from loguru import logger
from changedetectionio.notification.message_unpacker import HueyMessageUnpacker
from changedetectionio.notification_service import timestamp_to_localtime


class NotificationStateRetriever:
    """
    Service for retrieving notification state from various sources.

    Provides unified interface for accessing:
    - Pending notifications (queued + scheduled/retrying)
    - Failed notifications (dead letter queue)
    - Delivered notifications (audit trail)
    - Unified event timeline
    """

    # Retry configuration constants
    NOTIFICATION_RETRY_COUNT = 2  # Number of retries (initial attempt + 2 retries = 3 total)

    def __init__(self, huey, task_data_manager, task_manager):
        """
        Initialize state retriever service.

        Args:
            huey: Huey instance for queue/schedule access
            task_data_manager: Task data storage manager for retry attempts and delivered notifications
            task_manager: Task manager for result store and metadata access
        """
        self.huey = huey
        self.task_data_manager = task_data_manager
        self.task_manager = task_manager

    def get_pending_notifications_count(self):
        """
        Get count of pending notifications (immediate queue + scheduled/retrying).

        This includes:
        - Tasks in the immediate queue (ready to execute now)
        - Tasks in the schedule (waiting for retry or delayed execution)

        Supports FileStorage, SqliteStorage, and RedisStorage backends.

        Returns:
            Integer count of pending notifications, or None if unable to determine
        """
        if self.huey is None or self.task_manager is None:
            return 0

        try:
            # Get counts using task manager (polymorphic, backend-agnostic)
            queue_count, schedule_count = self.task_manager.count_storage_items()

            total_count = queue_count + schedule_count

            if queue_count > 0:
                logger.debug(f"Pending notifications - queue: {queue_count}")
            if schedule_count > 0:
                logger.debug(f"Pending notifications - schedule: {schedule_count}")
            if total_count > 0:
                logger.info(f"Total pending/retrying notifications: {total_count}")

            return total_count

        except Exception as e:
            logger.error(f"Error getting pending notification count: {e}", exc_info=True)
            return None  # Unable to determine

    def get_pending_notifications(self, limit=50):
        """
        Get list of pending/retrying notifications from queue and schedule.

        Args:
            limit: Maximum number to return (default: 50)

        Returns:
            List of dicts with pending notification info
        """
        if self.huey is None:
            return []

        pending = []

        try:
            # Use Huey's built-in methods to get queued and scheduled items
            # These methods return pickled bytes that need to be unpickled

            # Get queued tasks (immediate execution)
            if hasattr(self.huey.storage, 'enqueued_items'):
                try:
                    queued_items = list(self.huey.storage.enqueued_items(limit=limit))
                    for queued_bytes in queued_items:
                        if len(pending) >= limit:
                            break

                        # Use centralized unpacker
                        result = HueyMessageUnpacker.unpack_queued_notification(queued_bytes, self.huey)
                        if result is None:
                            continue

                        task_id, notification_data = result

                        # Get metadata for timestamp
                        metadata = self._get_task_metadata(task_id) if task_id else None
                        queued_timestamp = metadata.get('timestamp') if metadata else None

                        # Format timestamp for display
                        queued_at_formatted = timestamp_to_localtime(queued_timestamp) if queued_timestamp else 'Unknown'

                        pending.append({
                            'status': 'queued',
                            'watch_url': notification_data.get('watch_url', 'Unknown'),
                            'watch_uuid': notification_data.get('uuid'),
                            'task_id': task_id,
                            'queued_at': queued_timestamp,
                            'queued_at_formatted': queued_at_formatted,
                        })
                except Exception as e:
                    logger.debug(f"Error getting queued items: {e}")

            # Get scheduled tasks (retrying)
            if hasattr(self.huey.storage, 'scheduled_items'):
                try:
                    scheduled_items = list(self.huey.storage.scheduled_items(limit=limit))
                    for scheduled_bytes in scheduled_items:
                        if len(pending) >= limit:
                            break

                        # Use centralized unpacker
                        result = HueyMessageUnpacker.unpack_scheduled_notification(scheduled_bytes, self.huey)
                        if result is None:
                            continue

                        task_id, notification_data, eta = result

                        # Calculate retry timing using unpacker utility
                        retry_in_seconds, eta_formatted = HueyMessageUnpacker.calculate_retry_timing(eta)

                        # Convert eta to Unix timestamp for JavaScript (with safety check)
                        retry_at_timestamp = None
                        if eta and hasattr(eta, 'timestamp'):
                            try:
                                # Huey stores ETA as naive datetime in UTC - need to add timezone info
                                if eta.tzinfo is None:
                                    # Naive datetime - assume it's UTC (Huey's default)
                                    import datetime
                                    eta = eta.replace(tzinfo=datetime.timezone.utc)
                                retry_at_timestamp = int(eta.timestamp())
                                logger.debug(f"ETA after timezone fix: {eta}, Timestamp: {retry_at_timestamp}")
                            except Exception as e:
                                logger.debug(f"Error converting eta to timestamp: {e}")

                        # Get original queued timestamp from metadata
                        metadata = self._get_task_metadata(task_id) if task_id else None
                        queued_timestamp = metadata.get('timestamp') if metadata else None

                        # Format timestamp for display
                        queued_at_formatted = timestamp_to_localtime(queued_timestamp) if queued_timestamp else 'Unknown'

                        # Get retry count from retry_attempts (using polymorphic task_data_manager)
                        # Retry number represents which retry this is (1st retry, 2nd retry, etc.)
                        # If there are N attempt files, we're currently on retry #N
                        retry_number = 1  # Default to 1 (first retry after initial failure)
                        total_attempts = self.NOTIFICATION_RETRY_COUNT + 1  # Initial attempt + retries
                        watch_uuid = notification_data.get('uuid')
                        retry_attempts = []
                        notification_urls = []

                        # Load retry attempts using polymorphic manager
                        if watch_uuid and self.task_data_manager is not None:
                            try:
                                retry_attempts = self.task_data_manager.load_retry_attempts(watch_uuid)

                                if len(retry_attempts) > 0:
                                    # Current retry number = number of attempt files
                                    # (1 file = 1st retry, 2 files = 2nd retry, etc.)
                                    retry_number = len(retry_attempts)
                                    logger.debug(f"Watch {watch_uuid[:8]}: Found {len(retry_attempts)} retry files, currently on retry #{retry_number}/{total_attempts}")

                                    # Extract notification_urls from latest retry attempt
                                    latest_attempt = retry_attempts[-1]
                                    attempt_notification_data = latest_attempt.get('notification_data', {})
                                    if attempt_notification_data:
                                        notification_urls = attempt_notification_data.get('notification_urls', [])
                                else:
                                    # No retry attempts yet - first retry
                                    retry_number = 1
                                    logger.debug(f"Watch {watch_uuid[:8]}: No retry attempts yet, first retry (retry #1/{total_attempts})")
                            except Exception as e:
                                logger.warning(f"Error reading retry attempts for {watch_uuid}: {e}, defaulting to attempt #1")
                                retry_number = 1  # Fallback to 1 on error

                        pending.append({
                            'status': 'retrying',
                            'watch_url': notification_data.get('watch_url', 'Unknown'),
                            'watch_uuid': notification_data.get('uuid'),
                            'retry_at': eta,
                            'retry_at_formatted': eta_formatted,
                            'retry_at_timestamp': retry_at_timestamp,
                            'retry_in_seconds': retry_in_seconds,
                            'task_id': task_id,
                            'queued_at': queued_timestamp,
                            'queued_at_formatted': queued_at_formatted,
                            'retry_number': retry_number,
                            'total_retries': total_attempts,
                            'retry_attempts': retry_attempts,
                            'notification_urls': notification_urls,
                        })
                except Exception as e:
                    logger.debug(f"Error getting scheduled items: {e}")

        except Exception as e:
            logger.error(f"Error getting pending notifications: {e}", exc_info=True)

        logger.debug(f"get_pending_notifications returning {len(pending)} items")
        return pending

    def get_delivered_notifications(self, limit=50):
        """
        Get list of delivered (successful) notifications (using polymorphic task_data_manager).

        Each successful notification is stored in the task data manager.

        Args:
            limit: Maximum number to return (default: 50)

        Returns:
            List of dicts with delivered notification info (newest first)
        """
        if self.task_data_manager is None:
            logger.debug("Task data manager not initialized")
            return []

        try:
            # Load using polymorphic manager (handles FileStorage, SQLiteStorage, RedisStorage)
            notifications = self.task_data_manager.load_delivered_notifications()

            # Apply limit
            if limit and len(notifications) > limit:
                notifications = notifications[:limit]

            return notifications

        except Exception as e:
            logger.debug(f"Unable to load delivered notifications: {e}")

        return []

    def get_last_successful_notification(self):
        """
        Get the most recent successful notification for reference.

        Returns:
            Dict with success info or None if no successful notifications yet
        """
        delivered = self.get_delivered_notifications(limit=1)
        return delivered[0] if delivered else None

    def get_failed_notifications(self, limit=100, max_age_days=30):
        """
        Get list of failed notification tasks from Huey's result store.

        Args:
            limit: Maximum number of failed tasks to return (default: 100)
            max_age_days: Auto-delete failed notifications older than this (default: 30 days)

        Returns:
            List of dicts containing failed notification info:
            - task_id: Huey task ID
            - timestamp: When the task failed
            - error: Error message
            - notification_data: Original notification data
            - watch_url: URL of the watch
            - watch_uuid: UUID of the watch
        """
        if self.huey is None or self.task_manager is None:
            return []

        failed_tasks = []
        import time

        try:
            # Query Huey's result storage for failed tasks using backend-agnostic helper
            cutoff_time = time.time() - (max_age_days * 86400)

            # Use helper function that works with all storage backends
            results = self.task_manager.enumerate_results()

            # Import Huey's Error class for checking failed tasks
            from huey.utils import Error as HueyError

            for task_id, result in results.items():
                if isinstance(result, (Exception, HueyError)):
                    # This is a failed task (either Exception or Huey Error object)
                    # Check if task is still scheduled for retry
                    # If it is, don't include it in failed list (still retrying)
                    if self.huey.storage:
                        try:
                            # Check if this task is in the schedule queue (still being retried)
                            task_still_scheduled = False

                            # Use Huey's built-in scheduled_items() method to get scheduled tasks
                            try:
                                if hasattr(self.huey.storage, 'scheduled_items'):
                                    scheduled_items = list(self.huey.storage.scheduled_items())
                                    for scheduled_bytes in scheduled_items:
                                        # Use centralized unpacker to extract just the task ID
                                        scheduled_task_id = HueyMessageUnpacker.extract_task_id_from_scheduled(scheduled_bytes)
                                        if scheduled_task_id == task_id:
                                            task_still_scheduled = True
                                            logger.debug(f"Task {task_id[:20]}... IS scheduled")
                                            break
                            except Exception as se:
                                logger.debug(f"Error checking schedule: {se}")

                            # Also check if task failed very recently (within last 5 seconds)
                            # Handles race condition where result is written before retry is scheduled
                            if not task_still_scheduled:
                                task_metadata = self._get_task_metadata(task_id)
                                if task_metadata:
                                    task_time = task_metadata.get('timestamp', 0)
                                    time_since_failure = time.time() - task_time if task_time else 999

                                    # If task failed very recently (< 5 seconds ago), it might still be scheduling a retry
                                    # Be conservative and don't count it as permanently failed yet
                                    if time_since_failure < 5:
                                        logger.debug(f"Task {task_id[:20]}... failed only {time_since_failure:.1f}s ago, might still be scheduling retry")
                                        task_still_scheduled = True  # Treat as potentially still retrying

                            # Skip this task if it's still scheduled for retry
                            if task_still_scheduled:
                                logger.debug(f"Task {task_id[:20]}... still scheduled for retry, not counting as failed yet")
                                continue
                            else:
                                logger.debug(f"Task {task_id[:20]}... NOT in schedule, counting as failed")
                        except Exception as e:
                            logger.debug(f"Error checking schedule for task {task_id}: {e}")

                    # Try to extract notification data from task metadata storage
                    try:
                        # Get task metadata from our metadata storage
                        task_metadata = self._get_task_metadata(task_id)
                        if task_metadata:
                            task_time = task_metadata.get('timestamp', 0)
                            notification_data = task_metadata.get('notification_data', {})

                            # Auto-cleanup old failed notifications to free memory
                            if task_time and task_time < cutoff_time:
                                logger.info(f"Auto-deleting old failed notification {task_id} (age: {(time.time() - task_time) / 86400:.1f} days)")
                                self.task_manager.delete_result(task_id)
                                self.task_manager.delete_task_metadata(task_id)
                                continue

                            # Format timestamp for display with locale awareness
                            timestamp_formatted = timestamp_to_localtime(task_time) if task_time else 'Unknown'
                            days_ago = int((time.time() - task_time) / 86400) if task_time else 0

                            # Load retry attempts for this notification (using polymorphic task_data_manager)
                            retry_attempts = []
                            notification_watch_uuid = notification_data.get('uuid')
                            if notification_watch_uuid and self.task_data_manager is not None:
                                try:
                                    retry_attempts = self.task_data_manager.load_retry_attempts(notification_watch_uuid)
                                except Exception as e:
                                    logger.debug(f"Error loading retry attempts for {notification_watch_uuid}: {e}")

                            # Merge notification_data from latest retry attempt (has reloaded notification_urls)
                            if retry_attempts:
                                latest_attempt = retry_attempts[-1]
                                attempt_notification_data = latest_attempt.get('notification_data', {})
                                if attempt_notification_data:
                                    notification_data.update(attempt_notification_data)

                            failed_tasks.append({
                                'task_id': task_id,
                                'timestamp': task_time,
                                'timestamp_formatted': timestamp_formatted,
                                'days_ago': days_ago,
                                'error': str(result),
                                'notification_data': notification_data,
                                'retry_attempts': retry_attempts,
                            })
                    except Exception as e:
                        logger.error(f"Error extracting failed task data: {e}")

                if len(failed_tasks) >= limit:
                    break

        except Exception as e:
            logger.error(f"Error querying failed notifications: {e}")

        return failed_tasks

    def get_all_notification_events(self, limit=100):
        """
        Get ALL notification events in a unified format for timeline view.
        Returns successful deliveries, queued, retrying, and failed notifications.

        Returns list sorted by timestamp (newest first) with structure:
        {
            'id': 'task_id or unique_id',
            'status': 'delivered' | 'queued' | 'retrying' | 'failed',
            'timestamp': unix_timestamp,
            'timestamp_formatted': 'human readable',
            'watch_uuid': 'uuid',
            'watch_url': 'url',
            'watch_title': 'title or truncated url',
            'notification_urls': ['endpoint1', 'endpoint2'],
            'retry_number': 1,  # for retrying status
            'total_retries': 3,  # for retrying status
            'apprise_logs': 'logs text',
            'error': 'error text if failed'
        }
        """
        events = []

        # 1. Get delivered (successful) notifications (up to 100)
        delivered = self.get_delivered_notifications(limit=limit)
        for success in delivered:
            events.append({
                'id': success.get('task_id') or f"success-{success.get('timestamp', 0)}",
                'status': 'delivered',
                'timestamp': success.get('timestamp'),
                'timestamp_formatted': success.get('timestamp_formatted'),
                'watch_uuid': success.get('watch_uuid'),
                'watch_url': success.get('watch_url'),
                'watch_title': success.get('watch_url', 'Unknown')[:50],
                'notification_urls': success.get('notification_urls', []),
                'apprise_logs': '\n'.join(success.get('apprise_logs', [])) if isinstance(success.get('apprise_logs'), list) else success.get('apprise_logs', ''),
                'payload': success.get('payload'),
                'error': None
            })

        # 2. Get pending/queued notifications
        pending = self.get_pending_notifications(limit=limit)
        for item in pending:
            status = 'retrying' if item.get('status') == 'retrying' else 'queued'

            # Get apprise logs and payload for this task if available
            apprise_logs = None
            payload = None
            task_id = item.get('task_id')
            if task_id:
                log_data = self.get_task_apprise_log(task_id)
                if log_data and log_data.get('apprise_log'):
                    apprise_logs = log_data.get('apprise_log')
                # Get payload from retry attempts if available
                retry_attempts = item.get('retry_attempts', [])
                if retry_attempts:
                    payload = retry_attempts[-1].get('payload')

            events.append({
                'id': task_id,
                'status': status,
                'timestamp': item.get('queued_at'),
                'timestamp_formatted': item.get('queued_at_formatted'),
                'watch_uuid': item.get('watch_uuid'),
                'watch_url': item.get('watch_url'),
                'watch_title': item.get('watch_url', 'Unknown')[:50],
                'notification_urls': item.get('notification_urls', []) if item.get('notification_urls') else [],
                'retry_number': item.get('retry_number'),
                'total_retries': item.get('total_retries'),
                'retry_at': item.get('retry_at_timestamp'),
                'retry_at_formatted': item.get('retry_at_formatted'),
                'apprise_logs': apprise_logs,
                'payload': payload,
                'error': None
            })

        # 3. Get failed notifications (dead letter)
        failed = self.get_failed_notifications(limit=limit)
        for item in failed:
            # Get apprise logs and payload for failed tasks
            apprise_logs = None
            payload = None
            task_id = item.get('task_id')
            if task_id:
                log_data = self.get_task_apprise_log(task_id)
                if log_data and log_data.get('apprise_log'):
                    apprise_logs = log_data.get('apprise_log')

            # Get payload from retry attempts (has the most recent attempt data)
            retry_attempts = item.get('retry_attempts', [])
            if retry_attempts:
                payload = retry_attempts[-1].get('payload')

            events.append({
                'id': task_id,
                'status': 'failed',
                'timestamp': item.get('timestamp'),
                'timestamp_formatted': item.get('timestamp_formatted'),
                'watch_uuid': item.get('notification_data', {}).get('uuid'),
                'watch_url': item.get('notification_data', {}).get('watch_url'),
                'watch_title': item.get('notification_data', {}).get('watch_url', 'Unknown')[:50],
                'notification_urls': item.get('notification_data', {}).get('notification_urls', []),
                'apprise_logs': apprise_logs,
                'payload': payload,
                'error': item.get('error')
            })

        # Sort by timestamp (newest first)
        events.sort(key=lambda x: x.get('timestamp', 0) or 0, reverse=True)

        # HTML escape user-controlled fields to prevent XSS in UI
        from changedetectionio.jinja2_custom.safe_jinja import render_fully_escaped
        for event in events:
            # Escape apprise logs
            if event.get('apprise_logs'):
                event['apprise_logs'] = render_fully_escaped(event['apprise_logs'])

            # Escape error messages
            if event.get('error'):
                event['error'] = render_fully_escaped(event['error'])

            # Escape payload fields (notification title, body, format)
            if event.get('payload') and isinstance(event['payload'], dict):
                if event['payload'].get('notification_title'):
                    event['payload']['notification_title'] = render_fully_escaped(event['payload']['notification_title'])
                if event['payload'].get('notification_body'):
                    event['payload']['notification_body'] = render_fully_escaped(event['payload']['notification_body'])
                if event['payload'].get('notification_format'):
                    event['payload']['notification_format'] = render_fully_escaped(event['payload']['notification_format'])

        # Limit results
        return events[:limit]

    def get_task_apprise_log(self, task_id):
        """
        Get the Apprise log for a specific task.

        Returns dict with:
            - apprise_log: str (the log text)
            - task_id: str
            - watch_url: str (if available)
            - notification_urls: list (if available)
            - error: str (if failed)
        """
        if self.huey is None:
            return None

        try:
            # First check task metadata for notification data and logs
            metadata = self._get_task_metadata(task_id)

            # Also check Huey result for error info (failed tasks)
            from huey.utils import Error as HueyError
            error_info = None
            try:
                result = self.huey.result(task_id, preserve=True)
                if result and isinstance(result, (Exception, HueyError)):
                    error_info = str(result)
            except Exception as e:
                # If huey.result() raises an exception, that IS the error we want
                # (Huey raises the stored exception when calling result() on failed tasks)
                error_info = str(e)
                logger.debug(f"Got error from result for task {task_id}: {type(e).__name__}")

            if metadata:
                # Get apprise logs from metadata (could be 'apprise_logs' list or 'apprise_log' string)
                apprise_logs = metadata.get('apprise_logs', [])
                apprise_log_text = '\n'.join(apprise_logs) if isinstance(apprise_logs, list) else metadata.get('apprise_log', '')

                # If no logs in metadata but we have error_info, try to extract from error
                if not apprise_log_text and error_info and 'Apprise logs:' in error_info:
                    parts = error_info.split('Apprise logs:', 1)
                    if len(parts) > 1:
                        apprise_log_text = parts[1].strip()
                        # The exception string has escaped newlines (\n), convert to actual newlines
                        apprise_log_text = apprise_log_text.replace('\\n', '\n')
                        # Also remove trailing quotes and closing parens from exception repr
                        apprise_log_text = apprise_log_text.rstrip("')")
                        logger.debug(f"Extracted Apprise logs from error for task {task_id}: {len(apprise_log_text)} chars")

                    # Clean up error to not duplicate the Apprise logs
                    # Only show the main error message, not the logs again
                    error_parts = error_info.split('\nApprise logs:', 1)
                    if len(error_parts) > 1:
                        error_info = error_parts[0]  # Keep only the main error message

                # Use metadata for apprise_log and notification data, but also include error from result
                result = {
                    'task_id': task_id,
                    'apprise_log': apprise_log_text if apprise_log_text else 'No log available',
                    'watch_url': metadata.get('notification_data', {}).get('watch_url'),
                    'notification_urls': metadata.get('notification_data', {}).get('notification_urls', []),
                    'error': error_info if error_info else metadata.get('error'),
                }

                return result
            else:
                # Fallback: if no metadata, check result store
                try:
                    result = self.huey.result(task_id, preserve=True)
                    if result and isinstance(result, (Exception, HueyError)):
                        error = str(result)
                        return {
                            'task_id': task_id,
                            'apprise_log': f"Error: {error}",
                            'error': error
                        }
                except Exception as e:
                    error = str(e)
                    return {
                        'task_id': task_id,
                        'apprise_log': f"Error: {error}",
                        'error': error
                    }

            return None

        except Exception as e:
            logger.error(f"Error getting task apprise log: {e}")
            return None

    # Private helper methods

    def _get_task_metadata(self, task_id):
        """Get task metadata from task manager."""
        if self.task_manager is None:
            return None
        return self.task_manager.get_task_metadata(task_id)
