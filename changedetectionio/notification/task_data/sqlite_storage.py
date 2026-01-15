"""
SQLiteStorage backend task data manager for Huey notifications.

For SQLite-based storage (local disk only, not network storage).

Uses native SQLite tables to store retry attempts and delivered notifications
as JSON blobs for better performance and atomicity.
"""

import os
import json
import sqlite3
import time
from loguru import logger
from .base import HueyTaskDataStorageManager


class SqliteTaskDataStorageManager(HueyTaskDataStorageManager):
    """Task data manager for SQLiteStorage backend - uses SQLite tables for storage."""

    def __init__(self, storage, storage_path=None):
        super().__init__(storage, storage_path)
        self._init_tables()

    @property
    def storage_path(self):
        """
        Get storage path by extracting directory from SQLiteStorage's 'filename' attribute.

        Returns:
            str: Storage path (directory containing the SQLite database), or None if unavailable
        """
        # Use explicit path if provided (for testing)
        if self._explicit_storage_path:
            return self._explicit_storage_path

        # SQLiteStorage has a 'filename' attribute pointing to the .db file
        db_filename = getattr(self.storage, 'filename', None)
        if not db_filename:
            logger.warning("SQLiteStorage has no 'filename' attribute")
            return None

        # Extract directory from database filename
        storage_path = os.path.dirname(db_filename)

        if storage_path:
            logger.debug(f"SQLiteStorage path (from database directory): {storage_path}")
        else:
            logger.warning(f"Could not extract directory from SQLite filename: {db_filename}")

        return storage_path

    @property
    def db_filename(self):
        """Get the SQLite database filename."""
        return getattr(self.storage, 'filename', None)

    def _get_connection(self):
        """Get SQLite database connection."""
        if not self.db_filename:
            raise ValueError("No SQLite database filename available")
        return sqlite3.connect(self.db_filename)

    def _init_tables(self):
        """Initialize SQLite tables for retry attempts and delivered notifications."""
        if not self.db_filename:
            logger.warning("Cannot initialize tables - no database filename")
            return

        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Table for retry attempts (stores JSON blobs)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS notification_retry_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    watch_uuid TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL,
                    timestamp REAL NOT NULL,
                    data_json TEXT NOT NULL,
                    created_at REAL DEFAULT (strftime('%s', 'now'))
                )
            """)

            # Index for fast lookups by watch_uuid
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_retry_watch_uuid
                ON notification_retry_attempts(watch_uuid)
            """)

            # Table for delivered notifications (stores JSON blobs)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS notification_delivered (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL UNIQUE,
                    watch_uuid TEXT,
                    timestamp REAL NOT NULL,
                    data_json TEXT NOT NULL,
                    created_at REAL DEFAULT (strftime('%s', 'now'))
                )
            """)

            # Index for fast lookups and sorting by timestamp
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_delivered_timestamp
                ON notification_delivered(timestamp DESC)
            """)

            conn.commit()
            conn.close()
            logger.debug("Initialized SQLite tables for notification task data")

        except Exception as e:
            logger.error(f"Error initializing SQLite tables: {e}")

    def store_retry_attempt(self, watch_uuid, notification_data, error_message):
        """Store retry attempt in SQLite table as JSON blob."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Get current attempt number
            cursor.execute(
                "SELECT COUNT(*) FROM notification_retry_attempts WHERE watch_uuid = ?",
                (watch_uuid,)
            )
            attempt_number = cursor.fetchone()[0] + 1

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

            # Store as JSON blob
            cursor.execute("""
                INSERT INTO notification_retry_attempts
                (watch_uuid, attempt_number, timestamp, data_json)
                VALUES (?, ?, ?, ?)
            """, (watch_uuid, attempt_number, timestamp, json.dumps(retry_data)))

            conn.commit()
            conn.close()

            logger.debug(f"Stored retry attempt #{attempt_number} for watch {watch_uuid[:8]} in SQLite")
            return True

        except Exception as e:
            logger.error(f"Error storing retry attempt in SQLite: {e}")
            return False

    def load_retry_attempts(self, watch_uuid):
        """Load all retry attempts for a watch from SQLite table."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT data_json FROM notification_retry_attempts
                WHERE watch_uuid = ?
                ORDER BY attempt_number ASC
            """, (watch_uuid,))

            retry_attempts = []
            for row in cursor.fetchall():
                try:
                    attempt_data = json.loads(row[0])

                    # Format timestamp for display
                    attempt_time = attempt_data.get('timestamp')
                    if attempt_time:
                        from changedetectionio.notification_service import timestamp_to_localtime
                        attempt_data['timestamp_formatted'] = timestamp_to_localtime(attempt_time)

                    retry_attempts.append(attempt_data)
                except Exception as e:
                    logger.debug(f"Error parsing retry attempt JSON: {e}")

            conn.close()
            return retry_attempts

        except Exception as e:
            logger.debug(f"Error loading retry attempts from SQLite: {e}")
            return []

    def store_delivered_notification(self, task_id, notification_data, apprise_logs=None):
        """Store delivered notification in SQLite table as JSON blob."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            timestamp = time.time()
            watch_uuid = notification_data.get('watch_uuid')

            # Merge all data at top level
            delivery_data = {
                'task_id': task_id,
                'timestamp': timestamp,
                'apprise_logs': apprise_logs or []
            }
            delivery_data.update(notification_data)

            # Store as JSON blob
            cursor.execute("""
                INSERT INTO notification_delivered
                (task_id, watch_uuid, timestamp, data_json)
                VALUES (?, ?, ?, ?)
            """, (task_id, watch_uuid, timestamp, json.dumps(delivery_data)))

            conn.commit()
            conn.close()

            logger.debug(f"Stored delivered notification for task {task_id[:8]} in SQLite")
            return True

        except Exception as e:
            logger.error(f"Error storing delivered notification in SQLite: {e}")
            return False

    def load_delivered_notifications(self):
        """Load all delivered notifications from SQLite table."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT data_json FROM notification_delivered
                ORDER BY timestamp DESC
            """)

            delivered = []
            for row in cursor.fetchall():
                try:
                    delivery_data = json.loads(row[0])

                    # Format timestamp for display
                    delivery_time = delivery_data.get('timestamp')
                    if delivery_time:
                        from changedetectionio.notification_service import timestamp_to_localtime
                        delivery_data['timestamp_formatted'] = timestamp_to_localtime(delivery_time)

                    # Add event_id for UI consistency
                    delivery_data['event_id'] = delivery_data.get('task_id', '').replace('delivered-', '')

                    delivered.append(delivery_data)
                except Exception as e:
                    logger.debug(f"Error parsing delivered notification JSON: {e}")

            conn.close()
            return delivered

        except Exception as e:
            logger.debug(f"Error loading delivered notifications from SQLite: {e}")
            return []

    def cleanup_old_retry_attempts(self, cutoff_time):
        """Clean up old retry attempts from SQLite table."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                DELETE FROM notification_retry_attempts
                WHERE timestamp < ?
            """, (cutoff_time,))

            deleted_count = cursor.rowcount
            conn.commit()
            conn.close()

            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old retry attempts from SQLite")

            return deleted_count

        except Exception as e:
            logger.debug(f"Error cleaning up old retry attempts from SQLite: {e}")
            return 0

    def cleanup_old_delivered_notifications(self, cutoff_time):
        """Clean up old delivered notifications from SQLite table."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                DELETE FROM notification_delivered
                WHERE timestamp < ?
            """, (cutoff_time,))

            deleted_count = cursor.rowcount
            conn.commit()
            conn.close()

            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old delivered notifications from SQLite")

            return deleted_count

        except Exception as e:
            logger.debug(f"Error cleaning up old delivered notifications from SQLite: {e}")
            return 0

    def clear_retry_attempts(self, watch_uuid):
        """Clear all retry attempts for a specific watch from SQLite."""
        if not watch_uuid:
            return 0

        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Delete all retry attempts for this watch
            cursor.execute(
                "DELETE FROM notification_retry_attempts WHERE watch_uuid = ?",
                (watch_uuid,)
            )

            cleared_count = cursor.rowcount
            conn.commit()
            conn.close()

            if cleared_count > 0:
                logger.debug(f"Cleared {cleared_count} retry attempts for watch {watch_uuid[:8]} from SQLite")

            return cleared_count

        except Exception as e:
            logger.debug(f"Error clearing retry attempts for watch {watch_uuid} from SQLite: {e}")
            return 0

    def clear_all_data(self):
        """Clear all retry attempts and delivered notifications from SQLite."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Count before deletion
            cursor.execute("SELECT COUNT(*) FROM notification_retry_attempts")
            retry_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM notification_delivered")
            delivered_count = cursor.fetchone()[0]

            # Delete all
            cursor.execute("DELETE FROM notification_retry_attempts")
            cursor.execute("DELETE FROM notification_delivered")

            conn.commit()
            conn.close()

            return {
                'retry_attempts': retry_count,
                'delivered': delivered_count
            }

        except Exception as e:
            logger.error(f"Error clearing SQLite task data: {e}")
            return {'retry_attempts': 0, 'delivered': 0}
