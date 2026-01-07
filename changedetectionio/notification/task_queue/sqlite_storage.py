"""
SQLiteStorage backend task manager for Huey notifications.

WARNING: Only use on local disk storage, NOT on NFS/CIFS network storage!

Enhancements:
- SQLite provides ACID transactions (atomicity built-in)
- Hybrid mode: queue data in SQLite, retry attempts/success in JSON files
- JSON files use atomic writes from file_storage module
"""

from loguru import logger

from .base import HueyTaskManager


class SqliteStorageTaskManager(HueyTaskManager):
    """Task manager for SqliteStorage backend (local disk only)."""

    def __init__(self, storage, storage_path=None):
        """
        Initialize SQLite task manager.

        Args:
            storage: Huey SQLite storage instance
            storage_path: Directory for file-based data (retry attempts, success)
        """
        super().__init__(storage)
        self.storage_path = storage_path

    def enumerate_results(self):
        import pickle
        import sqlite3
        """Enumerate results by querying SQLite database."""
        results = {}

        if not hasattr(self.storage, 'filename') or self.storage.filename is None:
            logger.warning("SQLite storage has no filename, cannot enumerate results")
            return results

        try:
            conn = sqlite3.connect(self.storage.filename)
            cursor = conn.cursor()

            # SQLite storage uses 'kv' table for results, not 'results'
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='kv'")
            if not cursor.fetchone():
                conn.close()
                return results

            # Query all results from kv table
            # Huey SQLiteStorage stores everything in kv table with queue=<name>
            cursor.execute("SELECT key, value FROM kv WHERE queue = ?", (self.storage.name,))
            for row in cursor.fetchall():
                task_id = row[0]
                result_data = pickle.loads(row[1])
                results[task_id] = result_data

            conn.close()
        except Exception as e:
            logger.debug(f"Error enumerating SQLite results: {e}")

        return results

    def delete_result(self, task_id):
        """Delete result from SQLite database."""
        if not hasattr(self.storage, 'filename') or self.storage.filename is None:
            return False
        import sqlite3
        try:
            conn = sqlite3.connect(self.storage.filename)
            cursor = conn.cursor()
            # SQLite stores results in kv table
            cursor.execute("DELETE FROM kv WHERE queue = ? AND key = ?",
                          (self.storage.name, task_id))
            conn.commit()
            deleted = cursor.rowcount > 0
            conn.close()
            logger.debug(f"Deleted result from SQLite for task {task_id}: {deleted}")
            return deleted
        except Exception as e:
            logger.error(f"Error deleting SQLite result: {e}")
            return False

    def count_storage_items(self):
        """Count items by querying SQLite database."""
        queue_count = 0
        schedule_count = 0

        if not hasattr(self.storage, 'filename') or self.storage.filename is None:
            return queue_count, schedule_count
        import sqlite3
        try:
            conn = sqlite3.connect(self.storage.filename)
            cursor = conn.cursor()

            # SQLite uses 'task' table for queue, 'schedule' for scheduled items
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='task'")
            if cursor.fetchone():
                cursor.execute("SELECT COUNT(*) FROM task WHERE queue = ?", (self.storage.name,))
                queue_count = cursor.fetchone()[0]

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schedule'")
            if cursor.fetchone():
                cursor.execute("SELECT COUNT(*) FROM schedule WHERE queue = ?", (self.storage.name,))
                schedule_count = cursor.fetchone()[0]

            conn.close()
        except Exception as e:
            logger.debug(f"SQLite count error: {e}")

        return queue_count, schedule_count

    def clear_all_notifications(self):
        """Clear all notifications from SQLite database and file-based retry attempts/success."""
        cleared = {
            'queue': 0,
            'schedule': 0,
            'results': 0,
            'retry_attempts': 0,
            'task_metadata': 0,
            'delivered': 0
        }

        if not hasattr(self.storage, 'filename'):
            return cleared
        import sqlite3
        import os

        try:
            conn = sqlite3.connect(self.storage.filename)
            cursor = conn.cursor()

            # SQLite uses 'task' table for queue
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='task'")
            if cursor.fetchone():
                cursor.execute("DELETE FROM task WHERE queue = ?", (self.storage.name,))
                cleared['queue'] = cursor.rowcount

            # SQLite uses 'schedule' table
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schedule'")
            if cursor.fetchone():
                cursor.execute("DELETE FROM schedule WHERE queue = ?", (self.storage.name,))
                cleared['schedule'] = cursor.rowcount

            # SQLite uses 'kv' table for results
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='kv'")
            if cursor.fetchone():
                cursor.execute("DELETE FROM kv WHERE queue = ?", (self.storage.name,))
                cleared['results'] = cursor.rowcount

            # Check and clear task_metadata table if it exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='task_metadata'")
            if cursor.fetchone():
                cursor.execute("DELETE FROM task_metadata")
                cleared['task_metadata'] = cursor.rowcount

            conn.commit()
            conn.close()

            # Clear file-based retry attempts and success notifications
            # These are stored as JSON files even in SQLite mode (hybrid approach)
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
            logger.error(f"Error clearing SQLite notifications: {e}")

        return cleared

    def store_task_metadata(self, task_id, metadata):
        """Store task metadata in SQLite database."""
        import sqlite3
        import json
        import time

        if not hasattr(self.storage, 'filename'):
            return False

        try:
            conn = sqlite3.connect(self.storage.filename)
            cursor = conn.cursor()

            # Create table if it doesn't exist
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS task_metadata (
                    task_id TEXT PRIMARY KEY,
                    timestamp REAL,
                    metadata TEXT
                )
            """)

            metadata_with_id = {
                'task_id': task_id,
                'timestamp': time.time(),
                **metadata
            }

            cursor.execute(
                "INSERT OR REPLACE INTO task_metadata (task_id, timestamp, metadata) VALUES (?, ?, ?)",
                (task_id, time.time(), json.dumps(metadata_with_id))
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error storing SQLite task metadata: {e}")
            return False

    def get_task_metadata(self, task_id):
        """Retrieve task metadata from SQLite database."""
        import sqlite3
        import json

        if not hasattr(self.storage, 'filename'):
            return None

        try:
            conn = sqlite3.connect(self.storage.filename)
            cursor = conn.cursor()

            # Check if table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='task_metadata'")
            if not cursor.fetchone():
                conn.close()
                return None

            cursor.execute("SELECT metadata FROM task_metadata WHERE task_id = ?", (task_id,))
            row = cursor.fetchone()
            conn.close()

            if row:
                return json.loads(row[0])
            return None
        except Exception as e:
            logger.debug(f"Error retrieving SQLite task metadata: {e}")
            return None

    def delete_task_metadata(self, task_id):
        """Delete task metadata from SQLite database."""
        import sqlite3

        if not hasattr(self.storage, 'filename'):
            return False

        try:
            conn = sqlite3.connect(self.storage.filename)
            cursor = conn.cursor()

            # Check if table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='task_metadata'")
            if not cursor.fetchone():
                conn.close()
                return False

            cursor.execute("DELETE FROM task_metadata WHERE task_id = ?", (task_id,))
            conn.commit()
            deleted = cursor.rowcount > 0
            conn.close()
            return deleted
        except Exception as e:
            logger.debug(f"Error deleting SQLite task metadata: {e}")
            return False

    def cleanup_old_retry_attempts(self, cutoff_time):
        """Clean up old retry attempts from SQLite database."""
        import sqlite3

        if not hasattr(self.storage, 'filename'):
            return 0

        deleted_count = 0
        try:
            conn = sqlite3.connect(self.storage.filename)
            cursor = conn.cursor()

            # Check if retry_attempts table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='retry_attempts'")
            if not cursor.fetchone():
                conn.close()
                return 0

            # Delete old retry attempts
            cursor.execute("DELETE FROM retry_attempts WHERE timestamp < ?", (cutoff_time,))
            deleted_count = cursor.rowcount
            conn.commit()
            conn.close()

            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old retry attempts from SQLite")
        except Exception as e:
            logger.debug(f"Error cleaning up old SQLite retry attempts: {e}")

        return deleted_count
