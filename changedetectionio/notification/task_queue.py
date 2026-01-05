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
    Calculate retry delays with exponential backoff.

    Returns a tuple of delays for each retry attempt.
    Example: base delay 60s → (60, 120, 240, 480, ...)
    """
    if NOTIFICATION_RETRY_COUNT == 0:
        return tuple()

    delays = []
    for i in range(NOTIFICATION_RETRY_COUNT):
        delay = NOTIFICATION_RETRY_DELAY * (2 ** i)  # Exponential backoff
        delays.append(delay)

    return tuple(delays)


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


def get_pending_notifications(limit=20):
    """
    Get list of pending notifications in the queue (not yet processed or being retried).

    Args:
        limit: Maximum number of pending notifications to return (default: 20)

    Returns:
        List of dicts containing pending notification info:
        - task_id: Huey task ID
        - watch_url: URL of the watch (if available)
        - watch_uuid: UUID of the watch (if available)
        - queued_at: When the notification was queued (if available)
    """
    if huey is None:
        return []

    pending_tasks = []

    try:
        # Get pending tasks from the queue
        # Note: This accesses Huey's internal queue storage
        queue = huey.storage.queue

        # For FileHuey, the queue is a directory with files
        # For SqliteHuey/RedisHuey, we'd need different logic
        # This is a simplified implementation

        # Try to get queue length (varies by storage backend)
        try:
            queue_length = len(queue)
            if queue_length > 0:
                logger.info(f"Found {queue_length} pending notifications in queue")
        except:
            pass

        # Return simplified info - full introspection of pending tasks
        # is complex and varies by storage backend
        return []  # Simplified for now

    except Exception as e:
        logger.error(f"Error querying pending notifications: {e}")

    return pending_tasks


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
        # Note: This requires accessing Huey's internal storage
        from huey.storage import PeeweeStorage

        # Get all results and filter for errors
        # Huey stores results with task IDs as keys
        results = huey.storage.result_store.flush()
        cutoff_time = time.time() - (max_age_days * 86400)  # Convert days to seconds

        for task_id, result in results.items():
            if isinstance(result, Exception):
                # This is a failed task
                # Try to extract notification data from task args
                try:
                    task_data = huey.storage.get(task_id)
                    if task_data:
                        task_time = task_data.get('execute_time', 0)

                        # Auto-cleanup old failed notifications to free memory
                        if task_time and task_time < cutoff_time:
                            logger.info(f"Auto-deleting old failed notification {task_id} (age: {(time.time() - task_time) / 86400:.1f} days)")
                            huey.storage.delete(task_id)
                            continue

                        # Format timestamp for display with locale awareness
                        from changedetectionio.notification_service import timestamp_to_localtime
                        timestamp_formatted = timestamp_to_localtime(task_time) if task_time else 'Unknown'
                        days_ago = int((time.time() - task_time) / 86400) if task_time else 0

                        failed_tasks.append({
                            'task_id': task_id,
                            'timestamp': task_data.get('execute_time'),
                            'timestamp_formatted': timestamp_formatted,
                            'days_ago': days_ago,
                            'error': str(result),
                            'notification_data': task_data.get('args', [{}])[0] if task_data.get('args') else {},
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
        # Get the original task data
        task_data = huey.storage.get(task_id)

        if not task_data:
            logger.error(f"Task {task_id} not found in storage")
            return False

        # Extract notification data and re-queue
        notification_data = task_data.get('args', [{}])[0] if task_data.get('args') else {}

        if notification_data:
            # Queue it again with current settings
            send_notification_task(notification_data)

            # Remove from dead letter queue (it will go back if it fails again)
            huey.storage.delete(task_id)

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
        from huey.storage import PeeweeStorage

        # Get all failed tasks
        results = huey.storage.result_store.flush()

        for task_id, result in results.items():
            if isinstance(result, Exception):
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
        if n_object.get('notification_urls'):
            sent_obj = process_notification(n_object, datastore)

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

        logger.success(f"Notification sent successfully for {n_object.get('watch_url')}")
        return sent_obj

    except Exception as e:
        # Log error and update watch with error message (preserve original error handling)
        logger.error(f"Watch URL: {n_object.get('watch_url')}  Error {str(e)}")

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
def init_huey_task():
    """
    Decorate send_notification_task with Huey task decorator.

    Must be called after init_huey() so the decorator can be applied.
    """
    global send_notification_task
    if huey is None:
        raise RuntimeError("Huey not initialized! Call init_huey(datastore_path) first")

    # Apply Huey task decorator with exponential backoff retry settings
    retry_delays = get_retry_delays()
    send_notification_task = huey.task(
        retries=NOTIFICATION_RETRY_COUNT,
        retry_delay=retry_delays if retry_delays else NOTIFICATION_RETRY_DELAY
    )(send_notification_task)

    if retry_delays:
        logger.info(f"Notification retry configuration: {NOTIFICATION_RETRY_COUNT} retries with exponential backoff: {retry_delays}")
    else:
        logger.info(f"Notification retry configuration: No retries configured")


def cleanup_old_failed_notifications(max_age_days=30):
    """
    Clean up failed notifications older than max_age_days.

    Called on startup to prevent indefinite accumulation of old failures.

    Args:
        max_age_days: Delete failed notifications older than this (default: 30 days)

    Returns:
        Number of old failed notifications deleted
    """
    if huey is None:
        return 0

    import time
    deleted_count = 0

    try:
        from huey.storage import PeeweeStorage

        results = huey.storage.result_store.flush()
        cutoff_time = time.time() - (max_age_days * 86400)

        for task_id, result in results.items():
            if isinstance(result, Exception):
                try:
                    task_data = huey.storage.get(task_id)
                    if task_data:
                        task_time = task_data.get('execute_time', 0)
                        if task_time and task_time < cutoff_time:
                            huey.storage.delete(task_id)
                            deleted_count += 1
                except Exception as e:
                    logger.error(f"Error cleaning up old failed notification {task_id}: {e}")

        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old failed notifications (older than {max_age_days} days)")

    except Exception as e:
        logger.error(f"Error during failed notification cleanup: {e}")

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
