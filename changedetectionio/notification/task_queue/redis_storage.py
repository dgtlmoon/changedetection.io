"""
RedisStorage backend task manager for Huey notifications.

For distributed deployments with Redis.

Enhancements:
- Redis provides atomic operations (ACID-like semantics)
- Hybrid mode: queue data in Redis, retry attempts/success in JSON files
- JSON files use atomic writes from file_storage module
"""

from loguru import logger

from .base import HueyTaskManager


class RedisStorageTaskManager(HueyTaskManager):
    """Task manager for RedisStorage backend (distributed deployments)."""

    def __init__(self, storage, storage_path=None):
        """
        Initialize Redis task manager.

        Args:
            storage: Huey Redis storage instance
            storage_path: Directory for file-based data (retry attempts, success)
        """
        super().__init__(storage)
        self.storage_path = storage_path

    def enumerate_results(self):
        import pickle
        """Enumerate results using Redis commands."""
        results = {}

        if not hasattr(self.storage, 'conn'):
            return results

        try:
            # Redis stores results with keys like "{name}:result:{task_id}"
            name = self.storage.name
            pattern = f"{name}:result:*"

            # Get all result keys
            result_keys = self.storage.conn.keys(pattern)

            for key in result_keys:
                # Extract task_id from key
                task_id = key.decode('utf-8').split(':')[-1]

                # Get result data
                result_data = self.storage.conn.get(key)
                if result_data:
                    results[task_id] = pickle.loads(result_data)
        except Exception as e:
            logger.error(f"Error enumerating Redis results: {e}")

        return results

    def delete_result(self, task_id):
        """Delete result from Redis."""
        if not hasattr(self.storage, 'conn'):
            return False

        try:
            name = self.storage.name
            result_key = f"{name}:result:{task_id}"
            deleted = self.storage.conn.delete(result_key) > 0
            logger.debug(f"Deleted result from Redis for task {task_id}: {deleted}")
            return deleted
        except Exception as e:
            logger.error(f"Error deleting Redis result: {e}")
            return False

    def count_storage_items(self):
        """Count items using Redis commands."""
        queue_count = 0
        schedule_count = 0

        if not hasattr(self.storage, 'conn'):
            return queue_count, schedule_count

        try:
            name = self.storage.name

            # Queue is a list
            queue_count = self.storage.conn.llen(f"{name}:queue")

            # Schedule is a sorted set
            schedule_count = self.storage.conn.zcard(f"{name}:schedule")
        except Exception as e:
            logger.debug(f"Redis count error: {e}")

        return queue_count, schedule_count

    def clear_all_notifications(self):
        """Clear all notifications from Redis and file-based retry attempts/success."""
        cleared = {
            'queue': 0,
            'schedule': 0,
            'results': 0,
            'retry_attempts': 0,
            'task_metadata': 0,
            'delivered': 0
        }

        if not hasattr(self.storage, 'conn'):
            return cleared

        import os

        try:
            name = self.storage.name

            # Clear queue (list)
            cleared['queue'] = self.storage.conn.llen(f"{name}:queue")
            self.storage.conn.delete(f"{name}:queue")

            # Clear schedule (sorted set)
            cleared['schedule'] = self.storage.conn.zcard(f"{name}:schedule")
            self.storage.conn.delete(f"{name}:schedule")

            # Clear results (keys)
            result_keys = self.storage.conn.keys(f"{name}:result:*")
            if result_keys:
                cleared['results'] = len(result_keys)
                self.storage.conn.delete(*result_keys)

            # Clear metadata (keys)
            metadata_keys = self.storage.conn.keys(f"{name}:metadata:*")
            if metadata_keys:
                cleared['task_metadata'] = len(metadata_keys)
                self.storage.conn.delete(*metadata_keys)

            # Clear file-based retry attempts and success notifications
            # These are stored as JSON files even in Redis mode (hybrid approach)
            if self.storage_path:
                # Clear retry attempts
                attempts_dir = os.path.join(self.storage_path, 'retry_attempts')
                if os.path.exists(attempts_dir):
                    for f in os.listdir(attempts_dir):
                        if f.endswith('.json'):
                            os.remove(os.path.join(attempts_dir, f))
                            cleared['retry_attempts'] += 1

                # Clear delivered (success) notifications
                success_dir = os.path.join(self.storage_path, 'success')
                if os.path.exists(success_dir):
                    for f in os.listdir(success_dir):
                        if f.startswith('success-') and f.endswith('.json'):
                            os.remove(os.path.join(success_dir, f))
                            cleared['delivered'] += 1

        except Exception as e:
            logger.error(f"Error clearing Redis notifications: {e}")

        return cleared

    def store_task_metadata(self, task_id, metadata):
        """Store task metadata in Redis."""
        import json
        import time

        if not hasattr(self.storage, 'conn'):
            return False

        try:
            name = self.storage.name
            metadata_key = f"{name}:metadata:{task_id}"

            metadata_with_id = {
                'task_id': task_id,
                'timestamp': time.time(),
                **metadata
            }

            self.storage.conn.set(metadata_key, json.dumps(metadata_with_id))
            return True
        except Exception as e:
            logger.error(f"Error storing Redis task metadata: {e}")
            return False

    def get_task_metadata(self, task_id):
        """Retrieve task metadata from Redis."""
        import json

        if not hasattr(self.storage, 'conn'):
            return None

        try:
            name = self.storage.name
            metadata_key = f"{name}:metadata:{task_id}"

            data = self.storage.conn.get(metadata_key)
            if data:
                return json.loads(data.decode('utf-8') if isinstance(data, bytes) else data)
            return None
        except Exception as e:
            logger.debug(f"Error retrieving Redis task metadata: {e}")
            return None

    def delete_task_metadata(self, task_id):
        """Delete task metadata from Redis."""
        if not hasattr(self.storage, 'conn'):
            return False

        try:
            name = self.storage.name
            metadata_key = f"{name}:metadata:{task_id}"
            deleted = self.storage.conn.delete(metadata_key) > 0
            return deleted
        except Exception as e:
            logger.debug(f"Error deleting Redis task metadata: {e}")
            return False

    def cleanup_old_retry_attempts(self, cutoff_time):
        """Clean up old retry attempts from Redis."""
        if not hasattr(self.storage, 'conn'):
            return 0

        deleted_count = 0
        try:
            name = self.storage.name
            pattern = f"{name}:retry_attempts:*"

            # Get all retry attempt keys
            retry_keys = self.storage.conn.keys(pattern)

            for key in retry_keys:
                try:
                    # Get the timestamp from the key's data
                    data = self.storage.conn.get(key)
                    if data:
                        import json
                        attempt_data = json.loads(data.decode('utf-8') if isinstance(data, bytes) else data)
                        timestamp = attempt_data.get('timestamp', 0)

                        if timestamp < cutoff_time:
                            self.storage.conn.delete(key)
                            deleted_count += 1
                except Exception as ke:
                    logger.debug(f"Error checking retry attempt key: {ke}")

            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old retry attempts from Redis")
        except Exception as e:
            logger.debug(f"Error cleaning up old Redis retry attempts: {e}")

        return deleted_count
