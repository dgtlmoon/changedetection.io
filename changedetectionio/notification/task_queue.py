#!/usr/bin/env python3

"""
Notification Task Queue - Huey-based notification processing with retry

Defaults to FileHuey for maximum compatibility with NFS/CIFS network storage
commonly used by Synology/QNAP NAS users.

Environment Variables:
    QUEUE_STORAGE: 'file' (default), 'sqlite', or 'redis'
    REDIS_URL: Redis connection URL (only if QUEUE_STORAGE=redis)
"""

import os
import struct
from loguru import logger

# Get queue storage type from environment
QUEUE_STORAGE = os.getenv('QUEUE_STORAGE', 'file').lower()

# Get retry configuration from environment (with validation)
def _get_retry_config():
    """Get retry configuration from environment variables with validation."""
    import re

    # Default values
    default_retries = 3
    default_delay = 60

    # Get and validate NOTIFICATION_RETRY_COUNT (must be 0-10)
    retry_count_str = os.getenv('NOTIFICATION_RETRY_COUNT', str(default_retries))
    if re.match(r'^\d+$', retry_count_str):
        retry_count = int(retry_count_str)
        retry_count = max(0, min(10, retry_count))  # Clamp to 0-10
    else:
        logger.warning(f"Invalid NOTIFICATION_RETRY_COUNT '{retry_count_str}', using default {default_retries}")
        retry_count = default_retries

    # Get and validate NOTIFICATION_RETRY_DELAY (must be 10-3600 seconds)
    retry_delay_str = os.getenv('NOTIFICATION_RETRY_DELAY', str(default_delay))
    if re.match(r'^\d+$', retry_delay_str):
        retry_delay = int(retry_delay_str)
        retry_delay = max(10, min(3600, retry_delay))  # Clamp to 10-3600 seconds
    else:
        logger.warning(f"Invalid NOTIFICATION_RETRY_DELAY '{retry_delay_str}', using default {default_delay}")
        retry_delay = default_delay

    return retry_count, retry_delay

NOTIFICATION_RETRY_COUNT, NOTIFICATION_RETRY_DELAY = _get_retry_config()


def get_retry_delays():
    """
    Calculate retry delays with exponential backoff for display purposes.

    Returns a list of delays for each retry attempt.
    Example: base delay 60s → [60, 120, 240, 480, ...]

    Note: This is for display/reporting only. Actual exponential backoff
    is handled by Huey's backoff=2 parameter in the task decorator.
    """
    if NOTIFICATION_RETRY_COUNT == 0:
        return []

    delays = []
    for i in range(NOTIFICATION_RETRY_COUNT):
        delay = NOTIFICATION_RETRY_DELAY * (2 ** i)  # Exponential backoff
        delays.append(delay)

    return delays


def get_retry_config():
    """
    Get current retry configuration for display in UI.

    Returns:
        dict: {
            'retry_count': int,
            'retry_delay_seconds': int,  # Base delay
            'retry_delays': tuple,  # Actual delays for each retry
            'total_attempts': int,
            'total_time_seconds': int
        }
    """
    retry_delays = get_retry_delays()
    total_time = sum(retry_delays) if retry_delays else 0

    return {
        'retry_count': NOTIFICATION_RETRY_COUNT,
        'retry_delay_seconds': NOTIFICATION_RETRY_DELAY,
        'retry_delays': retry_delays,
        'total_attempts': NOTIFICATION_RETRY_COUNT + 1,  # initial + retries
        'total_time_seconds': total_time
    }


# Global Huey instance (initialized later with proper datastore path)
huey = None


def init_huey(datastore_path):
    """
    Initialize Huey instance with the correct datastore path.

    Must be called after datastore is initialized, using datastore.datastore_path

    Args:
        datastore_path: Path to the datastore directory (from ChangeDetectionStore instance)

    Returns:
        Huey instance configured for the specified storage backend
    """
    global huey

    # Common options for all queue storage types
    common_options = {
        'name': 'changedetection-notifications',
        'store_none': True,  # Only store results for failed tasks (exceptions), not successful ones
        'results': True,  # Enable result storage
        # Note: store_errors is deprecated in newer Huey versions, removed
    }

    # Default to FileHuey unless explicitly configured otherwise
    if QUEUE_STORAGE == 'file' or QUEUE_STORAGE not in ['sqlite', 'redis']:
        # FileHuey (default) - NAS-safe, works on all storage types
        from huey import FileHuey

        queue_path = os.path.join(datastore_path, 'notification-queue')

        # Create directory if it doesn't exist
        os.makedirs(queue_path, exist_ok=True)

        logger.info(f"Notification queue: FileHuey (NAS-safe, file-based) - DEFAULT")
        logger.info(f"  Queue storage path: {queue_path}")

        huey = FileHuey(
            path=queue_path,
            use_thread_lock=True,
            **common_options
        )

    elif QUEUE_STORAGE == 'sqlite':
        # SQLite storage - ONLY for local disk storage!
        # WARNING: Do NOT use on NFS/CIFS network storage
        from huey import SqliteHuey

        queue_file = os.path.join(datastore_path, 'notification-queue.db')
        logger.info(f"Notification queue: SqliteHuey (local storage only!) - {queue_file}")
        logger.warning("Ensure datastore is on LOCAL disk, not NFS/CIFS network storage!")

        huey = SqliteHuey(
            filename=queue_file,
            immediate=False,
            storage_kwargs={
                'journal_mode': 'WAL',
                'timeout': 10
            },
            **common_options
        )

    elif QUEUE_STORAGE == 'redis':
        # Redis storage - for distributed deployments
        from huey import RedisHuey

        redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
        logger.info(f"Notification queue: RedisHuey - {redis_url}")

        huey = RedisHuey(
            url=redis_url,
            **common_options
        )

    # Configure Huey's logger to only show INFO and above (reduce scheduler DEBUG spam)
    import logging
    huey_logger = logging.getLogger('huey')
    huey_logger.setLevel(logging.INFO)

    return huey


def _count_storage_items(storage, storage_type):
    """
    Count items in Huey storage (queue + schedule) based on storage backend type.

    Args:
        storage: Huey storage instance
        storage_type: Type name string (e.g., 'FileStorage', 'SqliteStorage', 'RedisStorage')

    Returns:
        Tuple of (queue_count, schedule_count)
    """
    queue_count = 0
    schedule_count = 0

    import os

    if storage_type == 'FileStorage':
        # FileStorage: Walk file directories
        try:
            if hasattr(storage, 'path'):
                # Count queue files
                queue_dir = os.path.join(storage.path, 'queue')
                if os.path.exists(queue_dir):
                    for root, dirs, files in os.walk(queue_dir):
                        queue_count += len([f for f in files if not f.startswith('.')])

                # Count schedule files
                schedule_dir = os.path.join(storage.path, 'schedule')
                if os.path.exists(schedule_dir):
                    for root, dirs, files in os.walk(schedule_dir):
                        schedule_count += len([f for f in files if not f.startswith('.')])
        except Exception as e:
            logger.debug(f"FileStorage count error: {e}")

    elif storage_type in ['SqliteStorage', 'SqliteHuey']:
        # SqliteStorage: Query database tables
        try:
            import sqlite3
            if hasattr(storage, 'filename'):
                conn = sqlite3.connect(storage.filename)
                cursor = conn.cursor()

                # Count queue
                cursor.execute("SELECT COUNT(*) FROM queue")
                queue_count = cursor.fetchone()[0]

                # Count schedule
                cursor.execute("SELECT COUNT(*) FROM schedule")
                schedule_count = cursor.fetchone()[0]

                conn.close()
        except Exception as e:
            logger.debug(f"SqliteStorage count error: {e}")

    elif storage_type in ['RedisStorage', 'RedisHuey']:
        # RedisStorage: Use Redis commands
        try:
            if hasattr(storage, 'conn'):
                # Queue is a list
                queue_count = storage.conn.llen(f"{storage.name}:queue")

                # Schedule is a sorted set
                schedule_count = storage.conn.zcard(f"{storage.name}:schedule")
        except Exception as e:
            logger.debug(f"RedisStorage count error: {e}")

    else:
        # Unknown storage type - try generic attributes
        try:
            if hasattr(storage, 'queue_size'):
                queue_count = storage.queue_size()
            elif hasattr(storage, 'queue'):
                queue_count = len(storage.queue)
        except Exception:
            pass

        try:
            if hasattr(storage, 'schedule'):
                schedule_count = len(storage.schedule)
        except Exception:
            pass

    return queue_count, schedule_count


def get_pending_notifications_count():
    """
    Get count of pending notifications (immediate queue + scheduled/retrying).

    This includes:
    - Tasks in the immediate queue (ready to execute now)
    - Tasks in the schedule (waiting for retry or delayed execution)

    Supports FileStorage, SqliteStorage, and RedisStorage backends.

    Returns:
        Integer count of pending notifications, or None if unable to determine
    """
    if huey is None:
        return 0

    try:
        # Detect storage backend type
        storage_type = type(huey.storage).__name__

        # Get counts using backend-specific logic
        queue_count, schedule_count = _count_storage_items(huey.storage, storage_type)

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


def get_pending_notifications(limit=50):
    """
    Get list of pending/retrying notifications from queue and schedule.

    Args:
        limit: Maximum number to return (default: 50)

    Returns:
        List of dicts with pending notification info
    """
    if huey is None:
        return []

    pending = []
    import os
    import pickle
    import time

    try:
        storage_type = type(huey.storage).__name__

        if storage_type == 'FileStorage' and hasattr(huey.storage, 'path'):
            # FileStorage: Read pickled task files
            storage_path = huey.storage.path

            # Get queued tasks (immediate)
            queue_dir = os.path.join(storage_path, 'queue')
            if os.path.exists(queue_dir):
                for root, dirs, files in os.walk(queue_dir):
                    for filename in files:
                        if filename.startswith('.') or len(pending) >= limit:
                            continue
                        filepath = os.path.join(root, filename)
                        try:
                            with open(filepath, 'rb') as f:
                                task_data = pickle.load(f)
                                notification_data = task_data.get('args', [{}])[0] if task_data.get('args') else {}
                                pending.append({
                                    'status': 'queued',
                                    'watch_url': notification_data.get('watch_url', 'Unknown'),
                                    'watch_uuid': notification_data.get('uuid'),
                                    'queued_at': task_data.get('execute_time'),
                                })
                        except Exception:
                            pass

            # Get scheduled tasks (retrying)
            schedule_dir = os.path.join(storage_path, 'schedule')
            if os.path.exists(schedule_dir):
                for root, dirs, files in os.walk(schedule_dir):
                    for filename in files:
                        if filename.startswith('.') or len(pending) >= limit:
                            continue
                        filepath = os.path.join(root, filename)
                        try:
                            with open(filepath, 'rb') as f:
                                task_data = pickle.load(f)
                                notification_data = task_data.get('args', [{}])[0] if task_data.get('args') else {}
                                eta = task_data.get('eta')
                                pending.append({
                                    'status': 'retrying',
                                    'watch_url': notification_data.get('watch_url', 'Unknown'),
                                    'watch_uuid': notification_data.get('uuid'),
                                    'retry_at': eta,
                                    'retry_in_seconds': int(eta - time.time()) if eta else 0,
                                })
                        except Exception:
                            pass

        elif storage_type in ['SqliteStorage', 'SqliteHuey'] and hasattr(huey.storage, 'filename'):
            # SqliteStorage: Query database
            import sqlite3
            conn = sqlite3.connect(huey.storage.filename)
            cursor = conn.cursor()

            # Get queued tasks
            cursor.execute("SELECT data FROM queue LIMIT ?", (limit,))
            for row in cursor.fetchall():
                try:
                    task_data = pickle.loads(row[0])
                    notification_data = task_data.get('args', [{}])[0] if task_data.get('args') else {}
                    pending.append({
                        'status': 'queued',
                        'watch_url': notification_data.get('watch_url', 'Unknown'),
                        'watch_uuid': notification_data.get('uuid'),
                    })
                except Exception:
                    pass

            # Get scheduled tasks
            cursor.execute("SELECT data, eta FROM schedule LIMIT ?", (limit - len(pending),))
            for row in cursor.fetchall():
                try:
                    task_data = pickle.loads(row[0])
                    notification_data = task_data.get('args', [{}])[0] if task_data.get('args') else {}
                    eta = row[1]
                    pending.append({
                        'status': 'retrying',
                        'watch_url': notification_data.get('watch_url', 'Unknown'),
                        'watch_uuid': notification_data.get('uuid'),
                        'retry_at': eta,
                        'retry_in_seconds': int(eta - time.time()) if eta else 0,
                    })
                except Exception:
                    pass

            conn.close()

        # Format timestamps for display
        from changedetectionio.notification_service import timestamp_to_localtime
        for item in pending:
            if item.get('queued_at'):
                item['queued_at_formatted'] = timestamp_to_localtime(item['queued_at'])
            if item.get('retry_at'):
                item['retry_at_formatted'] = timestamp_to_localtime(item['retry_at'])

    except Exception as e:
        logger.error(f"Error getting pending notifications: {e}", exc_info=True)

    return pending


def get_last_successful_notification():
    """
    Get the most recent successful notification for reference.

    Returns:
        Dict with success info or None if no successful notifications yet
    """
    if huey is None or not hasattr(huey.storage, 'path'):
        return None

    import os
    import json

    try:
        success_file = os.path.join(huey.storage.path, 'last_successful_notification.json')
        if os.path.exists(success_file):
            with open(success_file, 'r') as f:
                success_data = json.load(f)

                # Format timestamp for display
                from changedetectionio.notification_service import timestamp_to_localtime
                success_time = success_data.get('timestamp')
                if success_time:
                    success_data['timestamp_formatted'] = timestamp_to_localtime(success_time)

                return success_data
    except Exception as e:
        logger.debug(f"Unable to load last successful notification: {e}")

    return None


def get_failed_notifications(limit=100, max_age_days=30):
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
    if huey is None:
        return []

    failed_tasks = []
    import time

    try:
        # Query Huey's result storage for failed tasks
        # Different storage backends work differently
        cutoff_time = time.time() - (max_age_days * 86400)

        results = {}

        # Try to get results - method varies by storage backend
        try:
            # SqliteHuey/RedisHuey have result_store.flush()
            results = huey.storage.result_store.flush()
        except AttributeError:
            # FileStorage doesn't have result_store.flush()
            # Need to enumerate result files directly from filesystem
            import os
            import pickle

            try:
                # FileStorage stores results as pickled files in subdirectories
                # Path structure: {storage.path}/results/{hash_subdir}/...
                storage_path = huey.storage.path
                results_dir = os.path.join(storage_path, 'results')

                if os.path.exists(results_dir):
                    # Walk through all subdirectories to find result files
                    for root, dirs, files in os.walk(results_dir):
                        for filename in files:
                            if filename.startswith('.'):
                                continue

                            filepath = os.path.join(root, filename)
                            try:
                                # Read and unpickle the result
                                # Huey FileStorage format: 4-byte length + task_id + pickled data
                                with open(filepath, 'rb') as f:
                                    # Read the task ID header (length-prefixed)
                                    task_id_len_bytes = f.read(4)
                                    if len(task_id_len_bytes) < 4:
                                        raise EOFError("Incomplete header")
                                    task_id_len = struct.unpack('>I', task_id_len_bytes)[0]
                                    task_id_bytes = f.read(task_id_len)
                                    if len(task_id_bytes) < task_id_len:
                                        raise EOFError("Incomplete task ID")
                                    task_id = task_id_bytes.decode('utf-8')

                                    # Now unpickle the result data
                                    result_data = pickle.load(f)
                                    results[task_id] = result_data
                            except (pickle.UnpicklingError, EOFError) as e:
                                # Corrupted or incomplete result file
                                # This can happen if:
                                # - Process crashed during write
                                # - Disk full
                                # - Leftover from interrupted shutdown
                                file_size = os.path.getsize(filepath)
                                logger.warning(f"Corrupted result file {filename} ({file_size} bytes) - likely from interrupted write. Moving to lost-found.")
                                try:
                                    # Move to lost-found directory instead of deleting
                                    import shutil
                                    lost_found_dir = os.path.join(storage_path, 'lost-found', 'results')
                                    os.makedirs(lost_found_dir, exist_ok=True)

                                    # Add timestamp to filename to avoid collisions
                                    import time
                                    timestamp = int(time.time())
                                    lost_found_path = os.path.join(lost_found_dir, f"{filename}.{timestamp}.corrupted")

                                    shutil.move(filepath, lost_found_path)
                                    logger.info(f"Moved corrupted file to {lost_found_path}")
                                except Exception as move_err:
                                    logger.error(f"Unable to move corrupted file to lost-found: {move_err}")
                            except Exception as e:
                                logger.debug(f"Unable to read result file {filename}: {e}")
                # Note: Not logging when results_dir doesn't exist - this is normal when no failures yet
            except Exception as e:
                logger.debug(f"Unable to enumerate FileStorage results: {e}")

        # Import Huey's Error class for checking failed tasks
        from huey.utils import Error as HueyError

        for task_id, result in results.items():
            if isinstance(result, (Exception, HueyError)):
                # This is a failed task (either Exception or Huey Error object)
                # Try to extract notification data from task metadata storage
                try:
                    # Get task metadata from our metadata storage
                    task_metadata = _get_task_metadata(task_id)
                    if task_metadata:
                        task_time = task_metadata.get('timestamp', 0)
                        notification_data = task_metadata.get('notification_data', {})

                        # Auto-cleanup old failed notifications to free memory
                        if task_time and task_time < cutoff_time:
                            logger.info(f"Auto-deleting old failed notification {task_id} (age: {(time.time() - task_time) / 86400:.1f} days)")
                            huey.storage.delete(task_id)
                            _delete_task_metadata(task_id)
                            continue

                        # Format timestamp for display with locale awareness
                        from changedetectionio.notification_service import timestamp_to_localtime
                        timestamp_formatted = timestamp_to_localtime(task_time) if task_time else 'Unknown'
                        days_ago = int((time.time() - task_time) / 86400) if task_time else 0

                        # Load retry attempts for this notification (by watch_uuid)
                        retry_attempts = []
                        notification_watch_uuid = notification_data.get('uuid')
                        if notification_watch_uuid and hasattr(huey.storage, 'path'):
                            import os
                            import json
                            import glob

                            attempts_dir = os.path.join(huey.storage.path, 'retry_attempts')
                            if os.path.exists(attempts_dir):
                                attempt_pattern = os.path.join(attempts_dir, f"{notification_watch_uuid}.*.json")
                                for attempt_file in sorted(glob.glob(attempt_pattern)):
                                    try:
                                        with open(attempt_file, 'r') as f:
                                            attempt_data = json.load(f)
                                            # Format timestamp for display
                                            attempt_time = attempt_data.get('timestamp')
                                            if attempt_time:
                                                attempt_data['timestamp_formatted'] = timestamp_to_localtime(attempt_time)
                                            retry_attempts.append(attempt_data)
                                    except Exception as ae:
                                        logger.debug(f"Unable to load retry attempt file {attempt_file}: {ae}")

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


def retry_failed_notification(task_id):
    """
    Retry a failed notification by task ID.

    Removes the task from the dead letter queue and re-queues it.
    If it fails again, it will go back to the dead letter queue.

    Args:
        task_id: Huey task ID to retry

    Returns:
        True if successfully queued for retry, False otherwise
    """
    if huey is None:
        logger.error("Huey not initialized")
        return False

    try:
        # Get the original task metadata from our storage
        task_metadata = _get_task_metadata(task_id)

        if not task_metadata:
            logger.error(f"Task metadata for {task_id} not found in storage")
            return False

        # Extract notification data
        notification_data = task_metadata.get('notification_data', {})

        if notification_data:
            # Queue it again with current settings using queue_notification
            # which will store new metadata for the new task
            queue_notification(notification_data)

            # Remove from dead letter queue (it will go back if it fails again)
            huey.storage.delete(task_id)

            # Clean up old metadata
            _delete_task_metadata(task_id)

            logger.info(f"Re-queued failed notification task {task_id} and removed from dead letter queue")
            return True
        else:
            logger.error(f"No notification data found for task {task_id}")
            return False

    except Exception as e:
        logger.error(f"Error retrying notification {task_id}: {e}")
        return False


def retry_all_failed_notifications():
    """
    Retry all failed notifications in the dead letter queue.

    Returns:
        dict: {
            'success': int,  # Number of notifications successfully re-queued
            'failed': int,   # Number that failed to re-queue
            'total': int     # Total number processed
        }
    """
    if huey is None:
        return {'success': 0, 'failed': 0, 'total': 0}

    success_count = 0
    failed_count = 0

    try:
        from huey.utils import Error as HueyError

        # Get all failed tasks
        results = huey.storage.result_store.flush()

        for task_id, result in results.items():
            if isinstance(result, (Exception, HueyError)):
                # Try to retry this failed notification
                if retry_failed_notification(task_id):
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
        return {'success': success_count, 'failed': failed_count, 'total': success_count + failed_count}


def send_notification_task(n_object_dict):
    """
    Background task to send a notification with automatic retry on failure.

    Retries 3 times with 60 second delay between attempts.

    IMPORTANT: notification_urls and notification_format are RELOADED from the
    datastore at retry time. This allows operators to fix broken settings (e.g.,
    wrong SMTP server) and retry with corrected configuration.

    notification_title and notification_body are preserved from the original
    notification context to support special notifications (e.g., filter failure
    notifications with custom messages).

    Snapshot data (diff, watch_url, triggered_text, etc.) is preserved from
    the original notification trigger.

    Preserves all logic from the original notification_runner including:
    - Reloading notification_urls from current datastore state at retry time
    - notification_debug_log tracking
    - Signal emission on errors
    - Error handling and watch updates

    Args:
        n_object_dict: Serialized NotificationContextData as dict (snapshot data)

    Returns:
        List of sent notification objects with title, body, url

    Raises:
        Exception: Any error during notification sending (triggers retry)
    """
    from changedetectionio.notification_service import NotificationContextData
    from changedetectionio.notification.handler import process_notification
    from changedetectionio.flask_app import datastore, notification_debug_log, app
    from datetime import datetime
    import json

    # Reconstruct NotificationContextData from serialized dict
    n_object = NotificationContextData(initial_data=n_object_dict)

    now = datetime.now()
    sent_obj = None

    try:
        # ALWAYS reload notification_urls from current datastore state
        # This allows operators to fix broken notification settings (e.g., wrong SMTP server)
        # and retry failed notifications with the corrected configuration
        #
        # NOTE: We only reload notification_urls and notification_format.
        # We do NOT reload notification_title or notification_body because they might be
        # custom for special notifications (e.g., filter failure notifications have their own
        # specific title and body that should be preserved).
        watch_uuid = n_object.get('uuid')
        watch = None

        # Get current watch data if this is a watch notification (not a test notification)
        if watch_uuid and watch_uuid in datastore.data['watching']:
            watch = datastore.data['watching'][watch_uuid]

        # Reload notification_urls from current settings (watch-level or system-level)
        # This is the main goal: allow fixing broken SMTP servers, etc.
        if watch and watch.get('notification_urls'):
            n_object['notification_urls'] = watch.get('notification_urls')
        else:
            # Fallback to system-level notification_urls
            n_object['notification_urls'] = datastore.data['settings']['application'].get('notification_urls', {})

        # Reload notification_format from current settings
        if watch and watch.get('notification_format'):
            n_object['notification_format'] = watch.get('notification_format')
        else:
            n_object['notification_format'] = datastore.data['settings']['application'].get('notification_format')

        # NOTE: notification_title and notification_body are NOT reloaded here.
        # They are preserved from the original notification context to support special
        # notifications like filter failures that have custom titles and bodies.

        # Process and send the notification using shared datastore
        # Capture Apprise logs during send
        apprise_logs = []
        if n_object.get('notification_urls'):
            import logging
            import io

            # Create a string buffer to capture Apprise logs
            log_capture = io.StringIO()
            handler = logging.StreamHandler(log_capture)
            handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)

            # Add handler to Apprise logger
            apprise_logger = logging.getLogger('apprise')
            apprise_logger.addHandler(handler)

            try:
                sent_obj = process_notification(n_object, datastore)

                # Capture the logs with limits to prevent excessive growth
                log_output = log_capture.getvalue()
                if log_output:
                    apprise_logs = log_output.strip().split('\n')

                    # Limit: Keep only last 50 lines to prevent bloat
                    if len(apprise_logs) > 50:
                        apprise_logs = apprise_logs[-50:]

                    # Limit: Truncate each line to 500 chars max
                    apprise_logs = [line[:500] + '...' if len(line) > 500 else line for line in apprise_logs]
            finally:
                # Always remove the handler
                apprise_logger.removeHandler(handler)
                log_capture.close()

        # Clear any previous error on success
        watch_uuid = n_object.get('uuid')
        if watch_uuid and watch_uuid in datastore.data['watching']:
            datastore.update_watch(
                uuid=watch_uuid,
                update_obj={'last_notification_error': None}
            )

        # Add to notification debug log (preserve original logging)
        notification_debug_log.append("{} - SENDING - {}".format(now.strftime("%c"), json.dumps(sent_obj)))
        # Trim the log length
        while len(notification_debug_log) > 100:
            notification_debug_log.pop(0)

        # Clean up retry attempt files on success and store last successful notification
        try:
            import os
            import glob

            if huey and hasattr(huey.storage, 'path'):
                watch_uuid = n_object.get('uuid')
                if watch_uuid:
                    attempts_dir = os.path.join(huey.storage.path, 'retry_attempts')
                    if os.path.exists(attempts_dir):
                        # Delete all attempt files for this watch
                        attempt_pattern = os.path.join(attempts_dir, f"{watch_uuid}.*.json")
                        for attempt_file in glob.glob(attempt_pattern):
                            os.remove(attempt_file)
                        logger.debug(f"Cleaned up retry attempt files for successful watch {watch_uuid}")

                # Store last successful notification for reference
                # Note: This file is overwritten on each success (only keeps most recent)
                # Logs are limited to 50 lines x 500 chars = ~25KB max
                success_file = os.path.join(huey.storage.path, 'last_successful_notification.json')
                success_data = {
                    'timestamp': time.time(),
                    'watch_url': n_object.get('watch_url'),
                    'watch_uuid': n_object.get('uuid'),
                    'notification_urls': list(n_object.get('notification_urls', {}).keys()) if n_object.get('notification_urls') else [],
                    'apprise_logs': apprise_logs if apprise_logs else [],
                }
                with open(success_file, 'w') as f:
                    json.dump(success_data, f, indent=2)
        except Exception as cleanup_error:
            logger.debug(f"Unable to cleanup retry attempts: {cleanup_error}")

        logger.success(f"Notification sent successfully for {n_object.get('watch_url')}")
        return sent_obj

    except Exception as e:
        # Log error and update watch with error message (preserve original error handling)
        logger.error(f"Watch URL: {n_object.get('watch_url')}  Error {str(e)}")

        # Store retry attempt details with Apprise logs
        # Note: We use watch_uuid as the identifier since Huey doesn't expose task ID easily
        try:
            import time
            import os
            import uuid

            if huey and hasattr(huey.storage, 'path'):
                attempts_dir = os.path.join(huey.storage.path, 'retry_attempts')
                os.makedirs(attempts_dir, exist_ok=True)

                # Use watch UUID as identifier (or generate one for test notifications)
                watch_uuid = n_object.get('uuid', str(uuid.uuid4()))

                # Count existing attempts for this watch
                attempt_files = [f for f in os.listdir(attempts_dir) if f.startswith(f"{watch_uuid}.")]
                attempt_number = len(attempt_files) + 1

                # Store with timestamp to avoid collisions
                timestamp = int(time.time())
                attempt_file = os.path.join(attempts_dir, f"{watch_uuid}.{attempt_number}.{timestamp}.json")

                attempt_data = {
                    'watch_uuid': watch_uuid,
                    'attempt_number': attempt_number,
                    'timestamp': time.time(),
                    'watch_url': n_object.get('watch_url'),
                    'error': str(e),  # Includes Apprise logs from exception message
                    'will_retry': attempt_number <= NOTIFICATION_RETRY_COUNT
                }

                with open(attempt_file, 'w') as f:
                    json.dump(attempt_data, f, indent=2)

                logger.debug(f"Stored retry attempt {attempt_number} for watch {watch_uuid}")
        except Exception as store_error:
            logger.debug(f"Unable to store retry attempt: {store_error}")

        watch_uuid = n_object.get('uuid')

        # UUID wont be present when we submit a 'test' from the global settings
        if watch_uuid:
            try:
                if watch_uuid in datastore.data['watching']:
                    datastore.update_watch(
                        uuid=watch_uuid,
                        update_obj={'last_notification_error': "Notification error detected, goto notification log."}
                    )
            except Exception as update_error:
                logger.error(f"Failed to update watch error status: {update_error}")

        # Add error lines to debug log (preserve original logging)
        log_lines = str(e).splitlines()
        notification_debug_log.extend(log_lines)
        # Trim the log length
        while len(notification_debug_log) > 100:
            notification_debug_log.pop(0)

        # Send signal (preserve original signal emission)
        try:
            with app.app_context():
                app.config['watch_check_update_SIGNAL'].send(app_context=app, watch_uuid=watch_uuid)
        except Exception as signal_error:
            logger.error(f"Failed to send watch_check_update signal: {signal_error}")

        # Re-raise to trigger Huey retry
        raise


# Decorator will be applied after huey is initialized
# This is set up in init_huey_task()
def _store_task_metadata(task_id, n_object_dict):
    """Store notification metadata for a task so we can retrieve it later when task fails."""
    if not huey or not hasattr(huey.storage, 'path'):
        return

    try:
        import json
        metadata_dir = os.path.join(huey.storage.path, 'task_metadata')
        os.makedirs(metadata_dir, exist_ok=True)

        metadata_file = os.path.join(metadata_dir, f"{task_id}.json")
        metadata = {
            'task_id': task_id,
            'timestamp': time.time(),
            'notification_data': n_object_dict
        }

        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)
    except Exception as e:
        logger.debug(f"Unable to store task metadata: {e}")


def _get_task_metadata(task_id):
    """Retrieve notification metadata for a task ID."""
    if not huey or not hasattr(huey.storage, 'path'):
        return None

    try:
        import json
        metadata_dir = os.path.join(huey.storage.path, 'task_metadata')
        metadata_file = os.path.join(metadata_dir, f"{task_id}.json")

        if os.path.exists(metadata_file):
            with open(metadata_file, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.debug(f"Unable to load task metadata for {task_id}: {e}")

    return None


def _delete_task_metadata(task_id):
    """Delete task metadata file (cleanup after success or manual deletion)."""
    if not huey or not hasattr(huey.storage, 'path'):
        return

    try:
        metadata_dir = os.path.join(huey.storage.path, 'task_metadata')
        metadata_file = os.path.join(metadata_dir, f"{task_id}.json")

        if os.path.exists(metadata_file):
            os.remove(metadata_file)
    except Exception as e:
        logger.debug(f"Unable to delete task metadata for {task_id}: {e}")


def queue_notification(n_object_dict):
    """
    Queue a notification task and store its metadata for later retrieval.

    This is the main entry point for queueing notifications. It wraps
    send_notification_task() and stores the task metadata so we can
    retrieve notification details even after the task completes.

    Args:
        n_object_dict: Notification data dictionary

    Returns:
        Huey TaskResultWrapper with task ID
    """
    # Queue the task with Huey
    task_result = send_notification_task(n_object_dict)

    # Store metadata so we can retrieve it later
    if task_result and hasattr(task_result, 'id'):
        _store_task_metadata(task_result.id, n_object_dict)

    return task_result


def init_huey_task():
    """
    Decorate send_notification_task with Huey task decorator.

    Must be called after init_huey() so the decorator can be applied.
    """
    global send_notification_task
    if huey is None:
        raise RuntimeError("Huey not initialized! Call init_huey(datastore_path) first")

    # Apply Huey task decorator with exponential backoff retry settings
    # backoff=2 means each retry delay is 2x the previous (exponential backoff)
    send_notification_task = huey.task(
        retries=NOTIFICATION_RETRY_COUNT,
        retry_delay=NOTIFICATION_RETRY_DELAY,
        backoff=2  # Exponential backoff multiplier (60s → 120s → 240s → ...)
    )(send_notification_task)

    retry_delays = get_retry_delays()
    if retry_delays:
        logger.info(f"Notification retry configuration: {NOTIFICATION_RETRY_COUNT} retries with exponential backoff (base: {NOTIFICATION_RETRY_DELAY}s, delays: {retry_delays})")
    else:
        logger.info(f"Notification retry configuration: No retries configured")


def clear_all_notifications():
    """
    Clear ALL notifications from queue, schedule, results, and retry attempts.

    WARNING: This is a destructive operation that clears:
    - Immediate queue (pending notifications)
    - Schedule (retrying/delayed notifications)
    - Results (failed notifications)
    - Retry attempt files

    Returns:
        Dict with counts of cleared items
    """
    if huey is None:
        return {'error': 'Huey not initialized'}

    import os
    import shutil

    cleared = {
        'queue': 0,
        'schedule': 0,
        'results': 0,
        'retry_attempts': 0,
        'task_metadata': 0
    }

    try:
        storage_type = type(huey.storage).__name__

        if storage_type == 'FileStorage' and hasattr(huey.storage, 'path'):
            # FileStorage: Delete directory contents
            storage_path = huey.storage.path

            # Clear queue
            queue_dir = os.path.join(storage_path, 'queue')
            if os.path.exists(queue_dir):
                for root, dirs, files in os.walk(queue_dir):
                    for f in files:
                        if not f.startswith('.'):
                            os.remove(os.path.join(root, f))
                            cleared['queue'] += 1

            # Clear schedule
            schedule_dir = os.path.join(storage_path, 'schedule')
            if os.path.exists(schedule_dir):
                for root, dirs, files in os.walk(schedule_dir):
                    for f in files:
                        if not f.startswith('.'):
                            os.remove(os.path.join(root, f))
                            cleared['schedule'] += 1

            # Clear results
            results_dir = os.path.join(storage_path, 'results')
            if os.path.exists(results_dir):
                for root, dirs, files in os.walk(results_dir):
                    for f in files:
                        if not f.startswith('.'):
                            os.remove(os.path.join(root, f))
                            cleared['results'] += 1

            # Clear retry attempts
            attempts_dir = os.path.join(storage_path, 'retry_attempts')
            if os.path.exists(attempts_dir):
                for f in os.listdir(attempts_dir):
                    if f.endswith('.json'):
                        os.remove(os.path.join(attempts_dir, f))
                        cleared['retry_attempts'] += 1

            # Clear task metadata
            metadata_dir = os.path.join(storage_path, 'task_metadata')
            if os.path.exists(metadata_dir):
                for f in os.listdir(metadata_dir):
                    if f.endswith('.json'):
                        os.remove(os.path.join(metadata_dir, f))
                        cleared['task_metadata'] += 1

        elif storage_type in ['SqliteStorage', 'SqliteHuey'] and hasattr(huey.storage, 'filename'):
            # SqliteStorage: Delete from tables
            import sqlite3
            conn = sqlite3.connect(huey.storage.filename)
            cursor = conn.cursor()

            cursor.execute("DELETE FROM queue")
            cleared['queue'] = cursor.rowcount

            cursor.execute("DELETE FROM schedule")
            cleared['schedule'] = cursor.rowcount

            cursor.execute("DELETE FROM results")
            cleared['results'] = cursor.rowcount

            conn.commit()
            conn.close()

        elif storage_type in ['RedisStorage', 'RedisHuey'] and hasattr(huey.storage, 'conn'):
            # RedisStorage: Delete keys
            name = huey.storage.name

            # Clear queue (list)
            cleared['queue'] = huey.storage.conn.llen(f"{name}:queue")
            huey.storage.conn.delete(f"{name}:queue")

            # Clear schedule (sorted set)
            cleared['schedule'] = huey.storage.conn.zcard(f"{name}:schedule")
            huey.storage.conn.delete(f"{name}:schedule")

            # Clear results (hash or keys)
            # Note: This depends on how Huey stores results in Redis
            result_keys = huey.storage.conn.keys(f"{name}:result:*")
            if result_keys:
                cleared['results'] = len(result_keys)
                huey.storage.conn.delete(*result_keys)

        logger.warning(f"Cleared all notifications: {cleared}")
        return cleared

    except Exception as e:
        logger.error(f"Error clearing notifications: {e}", exc_info=True)
        return {'error': str(e)}


def cleanup_old_failed_notifications(max_age_days=30):
    """
    Clean up failed notifications and retry attempts older than max_age_days.

    Called on startup to prevent indefinite accumulation of old failures.

    Args:
        max_age_days: Delete failed notifications older than this (default: 30 days)

    Returns:
        Number of old failed notifications deleted
    """
    if huey is None:
        return 0

    import time
    import os
    deleted_count = 0

    try:
        # Use get_failed_notifications with auto-cleanup to handle this
        # It already has logic to delete old failed notifications
        # We just call it and let it do the cleanup
        cutoff_time = time.time() - (max_age_days * 86400)

        # FileStorage and other backends handle result storage differently
        # The get_failed_notifications function already handles cleanup
        # So we just trigger it here
        get_failed_notifications(limit=1000, max_age_days=max_age_days)

        # Also clean up old retry attempt files
        if hasattr(huey.storage, 'path'):
            attempts_dir = os.path.join(huey.storage.path, 'retry_attempts')
            if os.path.exists(attempts_dir):
                for filename in os.listdir(attempts_dir):
                    if filename.endswith('.json'):
                        filepath = os.path.join(attempts_dir, filename)
                        try:
                            file_mtime = os.path.getmtime(filepath)
                            if file_mtime < cutoff_time:
                                os.remove(filepath)
                                deleted_count += 1
                        except Exception as fe:
                            logger.debug(f"Unable to delete old retry attempt file {filename}: {fe}")

                if deleted_count > 0:
                    logger.info(f"Cleaned up {deleted_count} old retry attempt files (older than {max_age_days} days)")

        logger.info(f"Completed cleanup check for failed notifications older than {max_age_days} days")

    except Exception as e:
        logger.debug(f"Unable to cleanup old failed notifications: {e}")

    return deleted_count


def start_huey_consumer():
    """
    Start Huey consumer in-process in the current thread.

    Replaces the old notification_runner() thread with Huey's consumer
    that provides retry logic and persistent queuing.

    This function blocks and processes tasks in the current thread.
    Should be called in a background thread (daemon=True).
    """
    global huey

    if huey is None:
        raise RuntimeError("Huey not initialized! Call init_huey(datastore_path) first")

    logger.info(f"Starting Huey notification consumer (single-threaded)")

    # Clean up old failed notifications on startup
    cleanup_old_failed_notifications(max_age_days=30)

    try:
        from huey.consumer import Consumer

        # Create and run consumer in this thread
        # workers=1 with worker_type='thread' means Consumer processes tasks in its own thread
        # To avoid thread-in-thread, we use the Consumer's blocking mode in this thread
        consumer = Consumer(
            huey,
            workers=1,  # Process tasks in the consumer thread itself
            worker_type='thread',  # Use thread-based execution
            scheduler_interval=1,  # Poll queue every 1 second
            check_worker_health=False,  # Disable health checks for single-threaded mode
            # Disable signal handlers - we're in a background thread, not main process
            # The main Flask app will handle shutdown signals
        )

        # Override signal handler setup to do nothing (we're in a thread)
        consumer._set_signal_handlers = lambda: None

        consumer.run()  # This blocks and processes tasks in current thread

    except Exception as e:
        logger.error(f"Failed to start Huey consumer: {e}")
        raise


def start_huey_consumer_with_watchdog(app):
    """
    Start Huey consumer with automatic restart on crash.

    If the consumer thread crashes, it will automatically restart after 5 seconds.
    This ensures notifications continue to be processed even after errors.

    Handles shutdown signals via app.config.exit event (same pattern as other threads).

    Args:
        app: Flask app instance (for accessing app.config.exit shutdown signal)

    Note: Queued notifications are persistent (stored in files/database), so even
    if the consumer crashes, queued items are not lost and will be processed when
    the consumer restarts.
    """
    while not app.config.exit.is_set():
        try:
            logger.info("Huey consumer watchdog: Starting consumer")
            start_huey_consumer()
            # If consumer.run() exits normally (shouldn't happen), restart
            logger.warning("Huey consumer exited normally, restarting in 5 seconds...")
            # Use wait() instead of sleep() so we can wake up immediately on shutdown signal
            app.config.exit.wait(5)
        except Exception as e:
            logger.error(f"Huey consumer crashed: {e}")
            logger.error(f"Watchdog: Restarting consumer in 5 seconds...")
            # Use wait() instead of sleep() so we can wake up immediately on shutdown signal
            app.config.exit.wait(5)

    logger.info("Huey consumer watchdog: Shutdown signal received, exiting")
