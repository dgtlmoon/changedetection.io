"""
RedisStorage backend task data manager for Huey notifications.

For distributed deployments with Redis.

Uses native Redis keys to store retry attempts and delivered notifications
as JSON strings for better performance and native Redis operations.
"""

import json
import time
from loguru import logger
from .base import HueyTaskDataStorageManager


class RedisTaskDataStorageManager(HueyTaskDataStorageManager):
    """Task data manager for RedisStorage backend - uses Redis keys for storage."""

    def __init__(self, storage, storage_path=None, fallback_path=None):
        """
        Initialize Redis task data manager.

        Args:
            storage: Huey Redis storage instance
            storage_path: Optional explicit storage path (for testing)
            fallback_path: Fallback path when Redis has no local storage
                          (typically the global datastore path)
        """
        super().__init__(storage, storage_path)
        self._fallback_path = fallback_path

    @property
    def storage_path(self):
        """
        Get storage path for Redis backend.

        Redis stores EVERYTHING natively in Redis (keys + JSON strings).
        This property returns None because Redis doesn't use filesystem storage.

        All operations (store/load/cleanup) are implemented using native Redis commands
        and do not touch the filesystem.

        Returns:
            None - Redis uses native database storage, not filesystem
        """
        # Redis stores everything in Redis database, no filesystem path needed
        # If any code tries to use storage_path, it will get None and should fail fast
        return None

    @property
    def redis_conn(self):
        """Get Redis connection from storage."""
        return getattr(self.storage, 'conn', None)

    def _get_key_prefix(self):
        """Get Redis key prefix based on storage name."""
        name = getattr(self.storage, 'name', 'changedetection-notifications')
        return f"{name}:task_data"

    def store_retry_attempt(self, watch_uuid, notification_data, error_message):
        """Store retry attempt in Redis as JSON string."""
        if not self.redis_conn:
            logger.error("No Redis connection available")
            return False

        try:
            # Get current attempt number
            key_prefix = self._get_key_prefix()
            pattern = f"{key_prefix}:retry:{watch_uuid}:*"
            existing_keys = self.redis_conn.keys(pattern)
            attempt_number = len(existing_keys) + 1

            # Extract payload if present
            payload = notification_data.pop('payload', None) if isinstance(notification_data, dict) else None

            # Prepare retry data
            timestamp = time.time()
            retry_data = {
                'watch_uuid': watch_uuid,
                'timestamp': timestamp,
                'attempt_number': attempt_number,
                'error': error_message,
                'error_message': error_message,
                'notification_data': notification_data,
                'payload': payload
            }

            # Store as JSON string in Redis
            retry_key = f"{key_prefix}:retry:{watch_uuid}:{attempt_number}"
            self.redis_conn.set(retry_key, json.dumps(retry_data))

            # Set expiration (30 days) to prevent unbounded growth
            self.redis_conn.expire(retry_key, 30 * 24 * 60 * 60)

            logger.debug(f"Stored retry attempt #{attempt_number} for watch {watch_uuid[:8]} in Redis")
            return True

        except Exception as e:
            logger.error(f"Error storing retry attempt in Redis: {e}")
            return False

    def load_retry_attempts(self, watch_uuid):
        """Load all retry attempts for a watch from Redis."""
        if not self.redis_conn:
            logger.debug("No Redis connection available")
            return []

        try:
            key_prefix = self._get_key_prefix()
            pattern = f"{key_prefix}:retry:{watch_uuid}:*"
            retry_keys = sorted(self.redis_conn.keys(pattern))

            retry_attempts = []
            for key in retry_keys:
                try:
                    data = self.redis_conn.get(key)
                    if data:
                        attempt_data = json.loads(data.decode('utf-8') if isinstance(data, bytes) else data)

                        # Format timestamp for display
                        attempt_time = attempt_data.get('timestamp')
                        if attempt_time:
                            from changedetectionio.notification_service import timestamp_to_localtime
                            attempt_data['timestamp_formatted'] = timestamp_to_localtime(attempt_time)

                        retry_attempts.append(attempt_data)
                except Exception as e:
                    logger.debug(f"Error parsing retry attempt from Redis: {e}")

            return retry_attempts

        except Exception as e:
            logger.debug(f"Error loading retry attempts from Redis: {e}")
            return []

    def store_delivered_notification(self, task_id, notification_data, apprise_logs=None):
        """Store delivered notification in Redis as JSON string."""
        if not self.redis_conn:
            logger.error("No Redis connection available")
            return False

        try:
            timestamp = time.time()

            # Merge all data at top level
            delivery_data = {
                'task_id': task_id,
                'timestamp': timestamp,
                'apprise_logs': apprise_logs or []
            }
            delivery_data.update(notification_data)

            # Store as JSON string in Redis
            key_prefix = self._get_key_prefix()
            delivery_key = f"{key_prefix}:delivered:{task_id}"
            self.redis_conn.set(delivery_key, json.dumps(delivery_data))

            # Set expiration (30 days) to prevent unbounded growth
            self.redis_conn.expire(delivery_key, 30 * 24 * 60 * 60)

            # Add to sorted set for time-ordered retrieval
            delivered_index = f"{key_prefix}:delivered:index"
            self.redis_conn.zadd(delivered_index, {task_id: timestamp})

            logger.debug(f"Stored delivered notification for task {task_id[:8]} in Redis")
            return True

        except Exception as e:
            logger.error(f"Error storing delivered notification in Redis: {e}")
            return False

    def load_delivered_notifications(self):
        """Load all delivered notifications from Redis (newest first)."""
        if not self.redis_conn:
            logger.debug("No Redis connection available")
            return []

        try:
            key_prefix = self._get_key_prefix()
            delivered_index = f"{key_prefix}:delivered:index"

            # Get task IDs sorted by timestamp (newest first)
            task_ids = self.redis_conn.zrevrange(delivered_index, 0, -1)

            delivered = []
            for task_id in task_ids:
                try:
                    task_id_str = task_id.decode('utf-8') if isinstance(task_id, bytes) else task_id
                    delivery_key = f"{key_prefix}:delivered:{task_id_str}"
                    data = self.redis_conn.get(delivery_key)

                    if data:
                        delivery_data = json.loads(data.decode('utf-8') if isinstance(data, bytes) else data)

                        # Format timestamp for display
                        delivery_time = delivery_data.get('timestamp')
                        if delivery_time:
                            from changedetectionio.notification_service import timestamp_to_localtime
                            delivery_data['timestamp_formatted'] = timestamp_to_localtime(delivery_time)

                        # Add event_id for UI consistency
                        delivery_data['event_id'] = delivery_data.get('task_id', '').replace('delivered-', '')

                        delivered.append(delivery_data)
                except Exception as e:
                    logger.debug(f"Error parsing delivered notification from Redis: {e}")

            return delivered

        except Exception as e:
            logger.debug(f"Error loading delivered notifications from Redis: {e}")
            return []

    def cleanup_old_retry_attempts(self, cutoff_time):
        """Clean up old retry attempts from Redis."""
        if not self.redis_conn:
            return 0

        deleted_count = 0
        try:
            key_prefix = self._get_key_prefix()
            pattern = f"{key_prefix}:retry:*"
            retry_keys = self.redis_conn.keys(pattern)

            for key in retry_keys:
                try:
                    data = self.redis_conn.get(key)
                    if data:
                        attempt_data = json.loads(data.decode('utf-8') if isinstance(data, bytes) else data)
                        timestamp = attempt_data.get('timestamp', 0)

                        if timestamp < cutoff_time:
                            self.redis_conn.delete(key)
                            deleted_count += 1
                except Exception as e:
                    logger.debug(f"Error checking retry attempt key: {e}")

            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old retry attempts from Redis")

        except Exception as e:
            logger.debug(f"Error cleaning up old retry attempts from Redis: {e}")

        return deleted_count

    def cleanup_old_delivered_notifications(self, cutoff_time):
        """Clean up old delivered notifications from Redis."""
        if not self.redis_conn:
            return 0

        deleted_count = 0
        try:
            key_prefix = self._get_key_prefix()
            delivered_index = f"{key_prefix}:delivered:index"

            # Get all task IDs with timestamp < cutoff_time
            old_task_ids = self.redis_conn.zrangebyscore(delivered_index, 0, cutoff_time)

            for task_id in old_task_ids:
                try:
                    task_id_str = task_id.decode('utf-8') if isinstance(task_id, bytes) else task_id
                    delivery_key = f"{key_prefix}:delivered:{task_id_str}"

                    # Delete the data key
                    self.redis_conn.delete(delivery_key)

                    # Remove from sorted set
                    self.redis_conn.zrem(delivered_index, task_id)

                    deleted_count += 1
                except Exception as e:
                    logger.debug(f"Error deleting old delivered notification: {e}")

            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old delivered notifications from Redis")

        except Exception as e:
            logger.debug(f"Error cleaning up old delivered notifications from Redis: {e}")

        return deleted_count

    def clear_retry_attempts(self, watch_uuid):
        """Clear all retry attempts for a specific watch from Redis."""
        if not self.redis_conn or not watch_uuid:
            return 0

        try:
            key_prefix = self._get_key_prefix()

            # Find all retry attempt keys for this watch
            pattern = f"{key_prefix}:retry:{watch_uuid}:*"
            retry_keys = self.redis_conn.keys(pattern)

            cleared_count = 0
            if retry_keys:
                self.redis_conn.delete(*retry_keys)
                cleared_count = len(retry_keys)

            if cleared_count > 0:
                logger.debug(f"Cleared {cleared_count} retry attempts for watch {watch_uuid[:8]} from Redis")

            return cleared_count

        except Exception as e:
            logger.debug(f"Error clearing retry attempts for watch {watch_uuid} from Redis: {e}")
            return 0

    def clear_all_data(self):
        """Clear all retry attempts and delivered notifications from Redis."""
        if not self.redis_conn:
            return {'retry_attempts': 0, 'delivered': 0}

        try:
            key_prefix = self._get_key_prefix()

            # Count and delete retry attempts
            retry_pattern = f"{key_prefix}:retry:*"
            retry_keys = self.redis_conn.keys(retry_pattern)
            retry_count = len(retry_keys)
            if retry_keys:
                self.redis_conn.delete(*retry_keys)

            # Count and delete delivered notifications
            delivered_pattern = f"{key_prefix}:delivered:*"
            delivered_keys = self.redis_conn.keys(delivered_pattern)
            delivered_count = len(delivered_keys)
            if delivered_keys:
                self.redis_conn.delete(*delivered_keys)

            return {
                'retry_attempts': retry_count,
                'delivered': delivered_count
            }

        except Exception as e:
            logger.error(f"Error clearing Redis task data: {e}")
            return {'retry_attempts': 0, 'delivered': 0}
