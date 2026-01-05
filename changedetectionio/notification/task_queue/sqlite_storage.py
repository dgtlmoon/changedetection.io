"""
SQLiteStorage backend task manager for Huey notifications.

WARNING: Only use on local disk storage, NOT on NFS/CIFS network storage!
"""

from loguru import logger

from .base import HueyTaskManager


class SqliteStorageTaskManager(HueyTaskManager):
    """Task manager for SqliteStorage backend (local disk only)."""

    def enumerate_results(self):
        import pickle
        import sqlite3
        """Enumerate results by querying SQLite database."""
        results = {}

        if not hasattr(self.storage, 'filename'):
            return results

        try:
            conn = sqlite3.connect(self.storage.filename)
            cursor = conn.cursor()

            # Query all results from database
            cursor.execute("SELECT key, value FROM results")
            for row in cursor.fetchall():
                task_id = row[0]
                result_data = pickle.loads(row[1])
                results[task_id] = result_data

            conn.close()
        except Exception as e:
            logger.error(f"Error enumerating SQLite results: {e}")

        return results

    def delete_result(self, task_id):
        """Delete result from SQLite database."""
        if not hasattr(self.storage, 'filename'):
            return False
        import sqlite3
        try:
            conn = sqlite3.connect(self.storage.filename)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM results WHERE key = ?", (task_id,))
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

        if not hasattr(self.storage, 'filename'):
            return queue_count, schedule_count
        import sqlite3
        try:
            conn = sqlite3.connect(self.storage.filename)
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM queue")
            queue_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM schedule")
            schedule_count = cursor.fetchone()[0]

            conn.close()
        except Exception as e:
            logger.debug(f"SQLite count error: {e}")

        return queue_count, schedule_count

    def clear_all_notifications(self):
        """Clear all notifications from SQLite database."""
        cleared = {
            'queue': 0,
            'schedule': 0,
            'results': 0,
            'retry_attempts': 0,
            'task_metadata': 0
        }

        if not hasattr(self.storage, 'filename'):
            return cleared
        import sqlite3
        try:
            conn = sqlite3.connect(self.storage.filename)
            cursor = conn.cursor()

            cursor.execute("DELETE FROM queue")
            cleared['queue'] = cursor.rowcount

            cursor.execute("DELETE FROM schedule")
            cleared['schedule'] = cursor.rowcount

            cursor.execute("DELETE FROM results")
            cleared['results'] = cursor.rowcount

            conn.commit()
            conn.close()
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
