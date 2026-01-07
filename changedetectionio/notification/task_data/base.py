"""
Base class for managing Huey task data (retry attempts and delivered notifications).

This provides polymorphic storage for audit trail data that persists
independently of the Huey queue backend (FileStorage, SQLiteStorage, RedisStorage).
"""

from loguru import logger


class HueyTaskDataStorageManager:
    """
    Abstract base class for managing task data storage.

    Handles retry attempt audit trails and delivered notification confirmations
    that are stored as JSON files on disk, regardless of the Huey queue backend.
    """

    def __init__(self, storage, storage_path=None):
        """
        Initialize the task data storage manager.

        Args:
            storage: Huey storage instance (FileStorage, SQLiteStorage, or RedisStorage)
            storage_path: Optional explicit storage path (for testing)
        """
        self.storage = storage
        self._explicit_storage_path = storage_path

    @property
    def storage_path(self):
        """
        Get the storage path for this backend.

        This is where retry attempts and delivered notifications are stored as JSON files.
        Must be implemented by subclasses to handle backend-specific path logic.

        Returns:
            str: Path to storage directory, or None if unavailable
        """
        raise NotImplementedError(f"{self.__class__.__name__} must implement storage_path property")

    def store_retry_attempt(self, watch_uuid, notification_data, error_message):
        """
        Store a retry attempt as a JSON file for audit trail.

        Args:
            watch_uuid: UUID of the watch
            notification_data: Dict containing notification data
            error_message: Error message from the failed attempt

        Returns:
            bool: True if stored successfully
        """
        import os
        import time
        from .file_utils import _atomic_json_write

        storage_path = self.storage_path
        if not storage_path:
            logger.debug("No storage path available, cannot store retry attempt")
            return False

        try:
            attempts_dir = os.path.join(storage_path, 'retry_attempts')
            os.makedirs(attempts_dir, exist_ok=True)

            # Create unique filename with timestamp
            timestamp = time.time()
            attempt_number = len([f for f in os.listdir(attempts_dir)
                                 if f.startswith(f"{watch_uuid}.")]) + 1
            filename = f"{watch_uuid}.{attempt_number}.{int(timestamp)}.json"
            filepath = os.path.join(attempts_dir, filename)

            # Extract payload if it's in notification_data
            payload = notification_data.pop('payload', None) if isinstance(notification_data, dict) else None

            # Store retry attempt data
            retry_data = {
                'watch_uuid': watch_uuid,
                'timestamp': timestamp,
                'attempt_number': attempt_number,
                'error': error_message,  # Using 'error' for backward compatibility
                'error_message': error_message,  # Also keep error_message for clarity
                'notification_data': notification_data,
                'payload': payload  # What was attempted to be sent to Apprise
            }

            _atomic_json_write(filepath, retry_data)
            logger.debug(f"Stored retry attempt #{attempt_number} for watch {watch_uuid[:8]}")
            return True

        except Exception as e:
            logger.error(f"Error storing retry attempt: {e}")
            return False

    def load_retry_attempts(self, watch_uuid):
        """
        Load all retry attempts for a watch.

        Args:
            watch_uuid: UUID of the watch

        Returns:
            list: List of retry attempt dicts, sorted by timestamp
        """
        import os
        import glob
        from .file_utils import _safe_json_load

        storage_path = self.storage_path
        if not storage_path:
            return []

        try:
            attempts_dir = os.path.join(storage_path, 'retry_attempts')
            if not os.path.exists(attempts_dir):
                return []

            retry_attempts = []
            attempt_pattern = os.path.join(attempts_dir, f"{watch_uuid}.*.json")

            for attempt_file in sorted(glob.glob(attempt_pattern)):
                try:
                    attempt_data = _safe_json_load(attempt_file, 'retry_attempts', storage_path)
                    if attempt_data:
                        # Format timestamp for display
                        attempt_time = attempt_data.get('timestamp')
                        if attempt_time:
                            from changedetectionio.notification_service import timestamp_to_localtime
                            attempt_data['timestamp_formatted'] = timestamp_to_localtime(attempt_time)
                        retry_attempts.append(attempt_data)
                except Exception as e:
                    logger.debug(f"Unable to load retry attempt file {attempt_file}: {e}")

            return retry_attempts

        except Exception as e:
            logger.debug(f"Error loading retry attempts for {watch_uuid}: {e}")
            return []

    def store_delivered_notification(self, task_id, notification_data, apprise_logs=None):
        """
        Store a delivered notification confirmation for audit trail.

        Args:
            task_id: Huey task ID
            notification_data: Dict containing notification data
            apprise_logs: Optional Apprise logs from delivery

        Returns:
            bool: True if stored successfully
        """
        import os
        import time
        from .file_utils import _atomic_json_write

        storage_path = self.storage_path
        if not storage_path:
            logger.debug("No storage path available, cannot store delivered notification")
            return False

        try:
            success_dir = os.path.join(storage_path, 'success')
            os.makedirs(success_dir, exist_ok=True)

            # Create unique filename with timestamp
            timestamp = int(time.time() * 1000)  # milliseconds for uniqueness
            filename = f"success-{task_id}-{timestamp}.json"
            filepath = os.path.join(success_dir, filename)

            # Store delivery confirmation data
            # Merge notification_data fields at top level for backward compatibility
            delivery_data = {
                'task_id': task_id,
                'timestamp': time.time(),
                'apprise_logs': apprise_logs or []
            }
            # Merge notification_data fields (watch_url, watch_uuid, notification_urls, payload)
            delivery_data.update(notification_data)

            _atomic_json_write(filepath, delivery_data)
            logger.debug(f"Stored delivered notification confirmation for task {task_id[:8]}")
            return True

        except Exception as e:
            logger.error(f"Error storing delivered notification: {e}")
            return False

    def load_delivered_notifications(self):
        """
        Load all delivered notification confirmations.

        Returns:
            list: List of delivered notification dicts, sorted by timestamp (newest first)
        """
        import os
        from .file_utils import _safe_json_load

        storage_path = self.storage_path
        if not storage_path:
            return []

        try:
            success_dir = os.path.join(storage_path, 'success')
            if not os.path.exists(success_dir):
                return []

            delivered = []
            for filename in os.listdir(success_dir):
                if not filename.startswith('success-') or not filename.endswith('.json'):
                    continue

                filepath = os.path.join(success_dir, filename)
                try:
                    delivery_data = _safe_json_load(filepath, 'success', storage_path)
                    if delivery_data:
                        # Format timestamp for display
                        delivery_time = delivery_data.get('timestamp')
                        if delivery_time:
                            from changedetectionio.notification_service import timestamp_to_localtime
                            delivery_data['timestamp_formatted'] = timestamp_to_localtime(delivery_time)

                        # Add event_id for UI consistency
                        delivery_data['event_id'] = filename.replace('success-', '').replace('.json', '')
                        delivered.append(delivery_data)
                except Exception as e:
                    logger.debug(f"Unable to load delivered notification file {filepath}: {e}")

            # Sort by timestamp, newest first
            delivered.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
            return delivered

        except Exception as e:
            logger.debug(f"Error loading delivered notifications: {e}")
            return []

    def cleanup_old_retry_attempts(self, cutoff_time):
        """
        Clean up retry attempt files older than cutoff time.

        Args:
            cutoff_time: Unix timestamp - files older than this will be deleted

        Returns:
            int: Number of files deleted
        """
        import os

        storage_path = self.storage_path
        if not storage_path:
            return 0

        deleted_count = 0
        try:
            attempts_dir = os.path.join(storage_path, 'retry_attempts')
            if not os.path.exists(attempts_dir):
                return 0

            for filename in os.listdir(attempts_dir):
                if not filename.endswith('.json'):
                    continue

                filepath = os.path.join(attempts_dir, filename)
                try:
                    # Check file modification time
                    file_mtime = os.path.getmtime(filepath)
                    if file_mtime < cutoff_time:
                        os.remove(filepath)
                        deleted_count += 1
                except Exception as e:
                    logger.debug(f"Error checking/deleting retry attempt file {filepath}: {e}")

            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old retry attempt files")

        except Exception as e:
            logger.debug(f"Error cleaning up old retry attempts: {e}")

        return deleted_count

    def cleanup_old_delivered_notifications(self, cutoff_time):
        """
        Clean up delivered notification files older than cutoff time.

        Args:
            cutoff_time: Unix timestamp - files older than this will be deleted

        Returns:
            int: Number of files deleted
        """
        import os

        storage_path = self.storage_path
        if not storage_path:
            return 0

        deleted_count = 0
        try:
            success_dir = os.path.join(storage_path, 'success')
            if not os.path.exists(success_dir):
                return 0

            for filename in os.listdir(success_dir):
                if not filename.startswith('success-') or not filename.endswith('.json'):
                    continue

                filepath = os.path.join(success_dir, filename)
                try:
                    # Check file modification time
                    file_mtime = os.path.getmtime(filepath)
                    if file_mtime < cutoff_time:
                        os.remove(filepath)
                        deleted_count += 1
                except Exception as e:
                    logger.debug(f"Error checking/deleting delivered notification file {filepath}: {e}")

            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old delivered notification files")

        except Exception as e:
            logger.debug(f"Error cleaning up old delivered notifications: {e}")

        return deleted_count

    def clear_retry_attempts(self, watch_uuid):
        """
        Clear all retry attempts for a specific watch.

        Called after successful notification delivery to clean up the audit trail.

        Args:
            watch_uuid: UUID of the watch to clear retry attempts for

        Returns:
            int: Number of retry attempts cleared
        """
        import os
        import glob

        storage_path = self.storage_path
        if not storage_path or not watch_uuid:
            return 0

        try:
            attempts_dir = os.path.join(storage_path, 'retry_attempts')
            if not os.path.exists(attempts_dir):
                return 0

            # Find all retry attempt files for this watch
            attempt_pattern = os.path.join(attempts_dir, f"{watch_uuid}.*.json")
            attempt_files = glob.glob(attempt_pattern)

            cleared_count = 0
            for attempt_file in attempt_files:
                try:
                    os.remove(attempt_file)
                    cleared_count += 1
                except Exception as e:
                    logger.debug(f"Error removing retry attempt file {attempt_file}: {e}")

            if cleared_count > 0:
                logger.debug(f"Cleared {cleared_count} retry attempts for watch {watch_uuid[:8]}")

            return cleared_count

        except Exception as e:
            logger.debug(f"Error clearing retry attempts for watch {watch_uuid}: {e}")
            return 0

    def clear_all_data(self):
        """
        Clear all retry attempts and delivered notifications.

        Returns:
            dict: Count of files cleared by type
        """
        import os

        storage_path = self.storage_path
        if not storage_path:
            return {'retry_attempts': 0, 'delivered': 0}

        cleared = {'retry_attempts': 0, 'delivered': 0}

        try:
            # Clear retry attempts
            attempts_dir = os.path.join(storage_path, 'retry_attempts')
            if os.path.exists(attempts_dir):
                for filename in os.listdir(attempts_dir):
                    if filename.endswith('.json'):
                        os.remove(os.path.join(attempts_dir, filename))
                        cleared['retry_attempts'] += 1

            # Clear delivered notifications
            success_dir = os.path.join(storage_path, 'success')
            if os.path.exists(success_dir):
                for filename in os.listdir(success_dir):
                    if filename.startswith('success-') and filename.endswith('.json'):
                        os.remove(os.path.join(success_dir, filename))
                        cleared['delivered'] += 1

        except Exception as e:
            logger.error(f"Error clearing task data: {e}")

        return cleared
