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
from changedetectionio.notification_service import NotificationContextData, _check_cascading_vars

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


def reload_retry_config():
    """Reload retry configuration from environment variables (useful for testing)"""
    global NOTIFICATION_RETRY_COUNT, NOTIFICATION_RETRY_DELAY
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


# ============================================================================
# Storage Backend Abstraction - Import Task Manager Classes
# ============================================================================

from .base import HueyTaskManager
from .file_storage import FileStorageTaskManager
from .sqlite_storage import SqliteStorageTaskManager
from .redis_storage import RedisStorageTaskManager


def _get_task_manager():
    """
    Factory function to get the appropriate task manager for the current storage backend.

    Returns:
        HueyTaskManager: Concrete task manager instance for the storage backend
    """
    if huey is None:
        return None

    storage_type = type(huey.storage).__name__

    if storage_type == 'FileStorage':
        storage_path = getattr(huey.storage, 'path', None)
        return FileStorageTaskManager(huey.storage, storage_path)
    elif storage_type in ['SqliteStorage', 'SqliteHuey']:
        # For SQLite, storage_path is the directory containing the .db file
        # Extract from filename: /path/to/notification-queue.db -> /path/to
        import os
        db_filename = getattr(huey.storage, 'filename', None)
        storage_path = os.path.dirname(db_filename) if db_filename else None
        return SqliteStorageTaskManager(huey.storage, storage_path)
    elif storage_type in ['RedisStorage', 'RedisHuey']:
        # For Redis, use global datastore path for file-based data
        return RedisStorageTaskManager(huey.storage, _datastore_path)
    else:
        logger.warning(f"Unknown storage type {storage_type}, operations may fail")
        return None


# Global Huey instance, datastore path, managers, and services (initialized later)
huey = None
_datastore_path = None  # For file-based retry attempts/success in all backends
task_data_manager = None  # Polymorphic manager for retry attempts and delivered notifications
retry_service = None  # Retry service for failed/scheduled notifications
state_retriever = None  # State retriever service for notification display


def init_huey(datastore_path):
    """
    Initialize Huey instance with the correct datastore path.

    Must be called after datastore is initialized, using datastore.datastore_path

    Args:
        datastore_path: Path to the datastore directory (from ChangeDetectionStore instance)

    Returns:
        Huey instance configured for the specified storage backend
    """
    global huey, _datastore_path, task_data_manager, state_retriever

    # Store datastore path globally for file-based retry attempts/success
    _datastore_path = datastore_path

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
            journal_mode='wal',  # Write-Ahead Logging for better concurrency
            timeout=10,  # Longer timeout for busy databases
            fsync=True,  # Force data to disk for reliability
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

    # Initialize task data storage manager (polymorphic - handles all storage backends)
    from changedetectionio.notification.task_data import create_task_data_storage_manager
    task_data_manager = create_task_data_storage_manager(huey.storage, fallback_path=_datastore_path)
    logger.info(f"Task data storage manager initialized: {type(task_data_manager).__name__}")

    # Initialize state retriever service
    from changedetectionio.notification.state_retriever import NotificationStateRetriever
    state_retriever = NotificationStateRetriever(huey, task_data_manager, _get_task_manager(), retry_count=NOTIFICATION_RETRY_COUNT)
    logger.info("Notification state retriever service initialized")

    # Configure Huey's logger to only show INFO and above (reduce scheduler DEBUG spam)
    # Don't do this when running under pytest - tests may want to see DEBUG logs
    import logging
    import sys
    if 'pytest' not in sys.modules:
        huey_logger = logging.getLogger('huey')
        huey_logger.setLevel(logging.INFO)

    return huey


def _count_storage_items():
    """
    Count items in Huey storage (queue + schedule) using task manager.

    Returns:
        Tuple of (queue_count, schedule_count)
    """
    task_manager = _get_task_manager()
    if task_manager is None:
        return 0, 0

    return task_manager.count_storage_items()


def get_pending_notifications_count():
    """
    Get count of pending notifications (immediate queue + scheduled/retrying).

    Delegates to NotificationStateRetriever for execution.

    Returns:
        Integer count of pending notifications, or None if unable to determine
    """
    retriever = _get_state_retriever()
    if retriever is None:
        return 0

    return retriever.get_pending_notifications_count()


def get_pending_notifications(limit=50):
    """
    Get list of pending/retrying notifications from queue and schedule.

    Delegates to NotificationStateRetriever for execution.

    Args:
        limit: Maximum number to return (default: 50)

    Returns:
        List of dicts with pending notification info
    """
    retriever = _get_state_retriever()
    if retriever is None:
        return []

    return retriever.get_pending_notifications(limit=limit)


def _enumerate_results():
    """
    Enumerate all results from Huey's result store.

    Uses polymorphic task manager to handle storage backend differences.

    Returns:
        dict: {task_id: result_data} for all stored results
    """
    task_manager = _get_task_manager()
    if task_manager is None:
        return {}

    return task_manager.enumerate_results()


def get_all_notification_events(limit=100):
    """
    Get ALL notification events in a unified format for timeline view.

    Delegates to NotificationStateRetriever for execution.

    Returns list sorted by timestamp (newest first) with events for:
    - delivered (successful) notifications
    - queued notifications
    - retrying notifications
    - failed notifications (dead letter)

    Args:
        limit: Maximum number of events to return (default: 100)

    Returns:
        List of event dicts with status, timestamp, watch info, logs, etc.
    """
    retriever = _get_state_retriever()
    if retriever is None:
        return []

    return retriever.get_all_notification_events(limit=limit)


# Removed: _cleanup_old_success_notifications - dead code, not used anywhere


def get_delivered_notifications(limit=50):
    """
    Get list of delivered (successful) notifications.

    Delegates to NotificationStateRetriever for execution.

    Args:
        limit: Maximum number to return (default: 50)

    Returns:
        List of dicts with delivered notification info (newest first)
    """
    retriever = _get_state_retriever()
    if retriever is None:
        return []

    return retriever.get_delivered_notifications(limit=limit)


def get_last_successful_notification():
    """
    Get the most recent successful notification for reference.

    Delegates to NotificationStateRetriever for execution.

    Returns:
        Dict with success info or None if no successful notifications yet
    """
    retriever = _get_state_retriever()
    if retriever is None:
        return None

    return retriever.get_last_successful_notification()


def get_failed_notifications(limit=100, max_age_days=30):
    """
    Get list of failed notification tasks from Huey's result store.

    Delegates to NotificationStateRetriever for execution.

    Args:
        limit: Maximum number of failed tasks to return (default: 100)
        max_age_days: Auto-delete failed notifications older than this (default: 30 days)

    Returns:
        List of dicts containing failed notification info
    """
    retriever = _get_state_retriever()
    if retriever is None:
        return []

    return retriever.get_failed_notifications(limit=limit, max_age_days=max_age_days)


def _delete_result(task_id):
    """
    Delete a result from Huey's result store using task manager.

    Args:
        task_id: Task ID to delete result for

    Returns:
        True if deleted successfully, False otherwise
    """
    task_manager = _get_task_manager()
    if task_manager is None:
        return False

    return task_manager.delete_result(task_id)


def get_task_apprise_log(task_id):
    """
    Get the Apprise log for a specific task.

    Delegates to NotificationStateRetriever for execution.

    Returns dict with:
        - apprise_log: str (the log text)
        - task_id: str
        - watch_url: str (if available)
        - notification_urls: list (if available)
        - error: str (if failed)
    """
    retriever = _get_state_retriever()
    if retriever is None:
        return None

    return retriever.get_task_apprise_log(task_id)


def _get_retry_service():
    """Get or create NotificationRetryService instance."""
    from changedetectionio.flask_app import datastore
    from changedetectionio.notification.retry_service import NotificationRetryService

    if huey is None or datastore is None:
        return None

    return NotificationRetryService(huey, datastore)


def _get_state_retriever():
    """Get NotificationStateRetriever instance."""
    if state_retriever is None:
        logger.error("State retriever not initialized")
        return None

    return state_retriever


def retry_notification_now(task_id):
    """
    Manually retry a scheduled/retrying notification immediately (used by "Send Now" button in UI).

    Revokes the scheduled task and executes the notification synchronously in the current thread.
    This is for manual retry from the notification dashboard, not automatic scheduled retry.

    Args:
        task_id: Huey task ID to retry immediately

    Returns:
        True if successfully executed, False otherwise
    """
    service = _get_retry_service()
    if service is None:
        logger.error("Retry service not available")
        return False

    return service.retry_now(task_id)


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
    service = _get_retry_service()
    if service is None:
        logger.error("Retry service not available")
        return False

    return service.retry_failed(task_id)


def retry_all_failed_notifications():
    """
    Retry all failed notifications in the dead letter queue.

    Delegates to NotificationRetryService for execution.

    Returns:
        dict: {
            'success': int,  # Number of notifications successfully re-queued
            'failed': int,   # Number that failed to re-queue
            'total': int     # Total number processed
        }
    """
    service = _get_retry_service()
    if service is None:
        return {'success': 0, 'failed': 0, 'total': 0}

    return service.retry_all_failed()



def _reload_notification_config(n_object, watch, datastore):
    """
    Reload notification_urls and notification_format with cascading priority.

    Priority: Watch settings > Tag settings > Global settings

    This is done on every send/retry to allow operators to fix broken
    notification settings and retry with corrected configuration.

    Delegates to NotificationRetryService for execution.

    Note: The datastore parameter is ignored since the retry service
    uses its own datastore instance. This signature is kept for compatibility.
    """
    service = _get_retry_service()
    if service is None:
        raise Exception("Retry service not available")

    service.reload_notification_config(n_object, watch)


def _capture_apprise_logs(callback):
    """
    Capture Apprise logs during notification send with size limits.

    Returns:
        tuple: (result from callback, list of log lines)
    """
    import logging
    import io

    log_capture = io.StringIO()
    handler = logging.StreamHandler(log_capture)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)

    apprise_logger = logging.getLogger('apprise')
    apprise_logger.addHandler(handler)

    try:
        result = callback()

        # Capture logs with limits to prevent bloat
        log_output = log_capture.getvalue()
        apprise_logs = []

        if log_output:
            apprise_logs = log_output.strip().split('\n')

            # Limit: Keep only last 50 lines
            if len(apprise_logs) > 50:
                apprise_logs = apprise_logs[-50:]

            # Limit: Truncate each line to 500 chars
            apprise_logs = [line[:500] + '...' if len(line) > 500 else line for line in apprise_logs]

        return result, apprise_logs
    finally:
        apprise_logger.removeHandler(handler)
        log_capture.close()


def _add_to_debug_log(notification_debug_log, message):
    """Add message to debug log and trim to max 100 entries."""
    notification_debug_log.append(message)
    while len(notification_debug_log) > 100:
        notification_debug_log.pop(0)


# _get_storage_path() removed - now using polymorphic task_data_manager instead


def _cleanup_retry_attempts(watch_uuid):
    """Delete all retry attempts for a watch after successful send (delegates to polymorphic task_data_manager)."""
    if not watch_uuid or task_data_manager is None:
        return

    task_data_manager.clear_retry_attempts(watch_uuid)


def _extract_notification_urls(n_object):
    """Extract notification URLs from n_object (handles dict or list)."""
    notif_urls = n_object.get('notification_urls', [])
    if isinstance(notif_urls, dict):
        return list(notif_urls.keys())
    elif isinstance(notif_urls, list):
        return notif_urls
    return []


def _store_successful_notification(n_object, apprise_logs, payload=None):
    """Store successful notification record and cleanup retry attempts (using polymorphic task_data_manager)."""
    import time

    if task_data_manager is None:
        logger.debug("Task data manager not initialized, cannot store successful notification")
        return

    watch_uuid = n_object.get('uuid')

    # Cleanup retry attempts for this watch
    _cleanup_retry_attempts(watch_uuid)

    # Prepare delivery data
    timestamp = time.time()
    unique_id = f"delivered-{watch_uuid}-{int(timestamp * 1000)}"

    # Prepare notification data with payload
    notification_data = {
        'watch_url': n_object.get('watch_url'),
        'watch_uuid': watch_uuid,
        'notification_urls': _extract_notification_urls(n_object),
        'payload': payload  # What was actually sent to Apprise
    }

    # Store using polymorphic manager (handles FileStorage, SQLiteStorage, RedisStorage)
    task_data_manager.store_delivered_notification(
        task_id=unique_id,
        notification_data=notification_data,
        apprise_logs=apprise_logs
    )


def _store_retry_attempt(n_object, error, payload=None):
    """Store retry attempt details after failure (using polymorphic task_data_manager)."""
    import uuid

    if task_data_manager is None:
        logger.debug("Task data manager not initialized, cannot store retry attempt")
        return

    watch_uuid = n_object.get('uuid', str(uuid.uuid4()))

    # Prepare notification data with payload
    notification_data = dict(n_object)
    if payload:
        notification_data['payload'] = payload

    # Store using polymorphic manager (handles FileStorage, SQLiteStorage, RedisStorage)
    task_data_manager.store_retry_attempt(
        watch_uuid=watch_uuid,
        notification_data=notification_data,
        error_message=str(error)
    )


def _handle_notification_error(watch_uuid, error, notification_debug_log, app, datastore):
    """Handle notification error: update watch, log error, emit signal."""
    # Update watch with error status
    if watch_uuid:
        try:
            if watch_uuid in datastore.data['watching']:
                datastore.update_watch(
                    uuid=watch_uuid,
                    update_obj={'last_notification_error': "Notification error detected, goto notification log."}
                )
        except Exception as update_error:
            logger.error(f"Failed to update watch error status: {update_error}")

    # Add error to debug log
    log_lines = str(error).splitlines()
    notification_debug_log.extend(log_lines)
    while len(notification_debug_log) > 100:
        notification_debug_log.pop(0)

    # Emit signal
    try:
        with app.app_context():
            app.config['watch_check_update_SIGNAL'].send(app_context=app, watch_uuid=watch_uuid)
    except Exception as signal_error:
        logger.error(f"Failed to send watch_check_update signal: {signal_error}")


def send_notification_task(n_object: NotificationContextData):
    """
    Background task to send a notification with automatic retry on failure.

    Retries 3 times with exponential backoff (60s, 120s, 240s).

    IMPORTANT: notification_urls and notification_format are RELOADED from the
    datastore on every attempt with cascading priority (Watch > Tag > System).
    This allows operators to fix broken settings and retry with corrected config.

    notification_title and notification_body are preserved from the original
    context to support special notifications (e.g., filter failure alerts).

    Args:
        n_object: NotificationContextData with snapshot data

    Returns:
        List of sent notification objects with title, body, url

    Raises:
        Exception: Any error during sending (triggers Huey retry)
    """
    from changedetectionio.notification.handler import process_notification
    from changedetectionio.flask_app import datastore, notification_debug_log, app
    from changedetectionio.notification_service import NotificationContextData
    from datetime import datetime
    import json

    from changedetectionio.notification.exceptions import (
        AppriseNotificationException,
        WatchNotFoundException,
        NotificationConfigurationException
    )

    # Wrap dict in NotificationContextData if needed (for retried tasks from Huey)
    if not isinstance(n_object, NotificationContextData):
        n_object = NotificationContextData(n_object)

    # Load watch
    watch = datastore.data['watching'].get(n_object.get('uuid'))
    if not watch:
        raise WatchNotFoundException(f"No watch found for uuid {n_object.get('uuid')}")

    try:
        # Reload notification config with cascading (Watch > Tag > System)
        _reload_notification_config(n_object, watch, datastore)

        # Send notification with Apprise log capture
        sent_objs, apprise_logs = _capture_apprise_logs(
            lambda: process_notification(n_object, datastore)
        )

        # Extract rendered notification from first item in list (has actual title/body after Jinja rendering)
        rendered_notification = None
        if sent_objs and len(sent_objs) > 0:
            first_sent = sent_objs[0]
            rendered_notification = {
                'notification_title': first_sent.get('title'),
                'notification_body': first_sent.get('body'),
                'notification_format': n_object.get('notification_format'),
                'notification_urls': n_object.get('notification_urls'),
            }

        # Log success
        now = datetime.now()
        _add_to_debug_log(
            notification_debug_log,
            f"{now.strftime('%c')} - SENDING - {json.dumps(sent_objs)}"
        )

        # Store success record with rendered notification payload
        try:
            _store_successful_notification(n_object, apprise_logs, payload=rendered_notification)
        except Exception as e:
            logger.error(f"Failed to store delivered notification: {e}", exc_info=True)

        logger.success(f"Notification sent successfully for {n_object.get('watch_url')}")
        return sent_objs

    except (WatchNotFoundException, NotificationConfigurationException) as e:
        # Non-recoverable error - don't retry, immediately mark as failed
        logger.error(f"Non-recoverable notification error: {str(e)}")

        # Store as failed (no retries) with error details
        attempted_payload = {
            'notification_urls': n_object.get('notification_urls'),
            'notification_title': n_object.get('notification_title'),
            'notification_body': n_object.get('notification_body'),
            'notification_format': n_object.get('notification_format'),
        }

        # Store in dead-letter queue immediately (no retries)
        try:
            _store_retry_attempt(n_object, e, payload=attempted_payload)
        except Exception as store_error:
            logger.debug(f"Unable to store failed notification: {store_error}")

        # Handle error: update watch, log, signal
        watch_uuid = n_object.get('uuid')
        _handle_notification_error(watch_uuid, e, notification_debug_log, app, datastore)

        # Re-raise to ensure Huey marks it as failed
        # But since this is non-recoverable, Huey will exhaust retries and mark as failed
        raise

    except AppriseNotificationException as e:
        # Recoverable Apprise error - retry with exponential backoff
        logger.error(f"Apprise notification failed (will retry): {str(e)}")

        # Get rendered notification payload from exception
        attempted_payload = None
        if e.sent_objs:
            first_sent = e.sent_objs[0]
            attempted_payload = {
                'notification_urls': n_object.get('notification_urls'),
                'notification_title': first_sent.get('title'),
                'notification_body': first_sent.get('body'),
                'notification_format': n_object.get('notification_format'),
            }
            logger.debug("Using fully rendered notification from AppriseNotificationException")
        else:
            # No sent_objs (shouldn't happen, but fallback)
            attempted_payload = {
                'notification_urls': n_object.get('notification_urls'),
                'notification_title': n_object.get('notification_title'),
                'notification_body': n_object.get('notification_body'),
                'notification_format': n_object.get('notification_format'),
            }

        # Store retry attempt
        try:
            _store_retry_attempt(n_object, e, payload=attempted_payload)
        except Exception as store_error:
            logger.debug(f"Unable to store retry attempt: {store_error}")

        # Handle error: update watch, log, signal
        watch_uuid = n_object.get('uuid')
        _handle_notification_error(watch_uuid, e, notification_debug_log, app, datastore)

        # Re-raise to trigger Huey retry
        raise

    except Exception as e:
        # Other unexpected errors - log and retry
        logger.error(f"Unexpected error sending notification: {str(e)}", exc_info=True)

        attempted_payload = {
            'notification_urls': n_object.get('notification_urls'),
            'notification_title': n_object.get('notification_title'),
            'notification_body': n_object.get('notification_body'),
            'notification_format': n_object.get('notification_format'),
        }

        # Store retry attempt
        try:
            _store_retry_attempt(n_object, e, payload=attempted_payload)
        except Exception as store_error:
            logger.debug(f"Unable to store retry attempt: {store_error}")

        # Handle error: update watch, log, signal
        watch_uuid = n_object.get('uuid')
        _handle_notification_error(watch_uuid, e, notification_debug_log, app, datastore)

        # Re-raise to trigger Huey retry
        raise


# Decorator will be applied after huey is initialized
# This is set up in init_huey_task()
def _store_task_metadata(task_id, n_object: NotificationContextData):
    """Store notification metadata using task manager."""
    task_manager = _get_task_manager()
    if task_manager is None:
        return False

    metadata = {'notification_data': n_object}
    return task_manager.store_task_metadata(task_id, metadata)


def _get_task_metadata(task_id):
    """Retrieve notification metadata using task manager."""
    task_manager = _get_task_manager()
    if task_manager is None:
        return None

    return task_manager.get_task_metadata(task_id)


def get_task_metadata(task_id):
    """
    Public wrapper to retrieve notification metadata by task ID.

    Args:
        task_id: Huey task ID

    Returns:
        Dict with task metadata if found, None otherwise
    """
    return _get_task_metadata(task_id)


def _delete_task_metadata(task_id):
    """Delete task metadata using task manager."""
    task_manager = _get_task_manager()
    if task_manager is None:
        return False

    return task_manager.delete_task_metadata(task_id)


def queue_notification(n_object: NotificationContextData):
    """
    Queue a notification task and store its metadata for later retrieval.

    This is the main entry point for queueing notifications. It wraps
    send_notification_task() and stores the task metadata so we can
    retrieve notification details even after the task completes.

    Args:
        n_object: NotificationContextData object

    Returns:
        Huey TaskResultWrapper with task ID
    """
    # Queue the task with Huey
    task_result = send_notification_task(n_object)

    # Store metadata so we can retrieve it later
    if task_result and hasattr(task_result, 'id'):
        _store_task_metadata(task_result.id, n_object)

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
    - Task metadata

    Returns:
        Dict with counts of cleared items
    """
    task_manager = _get_task_manager()
    if task_manager is None:
        return {'error': 'Huey not initialized'}

    try:
        cleared = task_manager.clear_all_notifications()
        logger.warning(f"Cleared all notifications: {cleared}")
        return cleared
    except Exception as e:
        logger.error(f"Error clearing notifications: {e}", exc_info=True)
        return {'error': str(e)}


def cleanup_old_failed_notifications(max_age_days=30, max_failed_count=None):
    """
    Clean up failed notifications with both age and count limits.

    Prevents unbounded growth of the dead letter queue.

    Called on startup to prevent indefinite accumulation of old failures.

    Args:
        max_age_days: Delete failed notifications older than this (default: 30 days)
        max_failed_count: Maximum number of failed notifications to keep (default: None = no limit)
                         Set to 1000 on startup for overflow protection.

    Returns:
        int: Total number of items deleted (failed notifications + retry attempts)
    """
    if huey is None:
        return 0

    import time

    deleted_counts = {
        'failed_by_age': 0,
        'failed_by_overflow': 0,
        'retry_attempts': 0
    }

    try:
        cutoff_time = time.time() - (max_age_days * 86400)

        # Step 1: Get all failed notifications (age-based cleanup happens inside this call)
        failed_before_age_cleanup = get_failed_notifications(limit=10000, max_age_days=max_age_days)

        # Step 2: If we still have too many failed notifications, delete oldest ones (overflow protection)
        # Only applies if max_failed_count is explicitly set
        if max_failed_count is not None and len(failed_before_age_cleanup) > max_failed_count:
            # Sort by timestamp (oldest first)
            failed_sorted = sorted(failed_before_age_cleanup, key=lambda x: x.get('timestamp', 0))

            # Delete excess (oldest notifications beyond the limit)
            to_delete = failed_sorted[:len(failed_before_age_cleanup) - max_failed_count]

            logger.warning(f"Dead letter queue overflow: {len(failed_before_age_cleanup)} failed notifications exceeds limit of {max_failed_count}")
            logger.warning(f"Deleting {len(to_delete)} oldest failed notifications for overflow protection")

            for task in to_delete:
                task_id = task.get('task_id')
                try:
                    # Delete result and metadata
                    _delete_result(task_id)
                    _delete_task_metadata(task_id)
                    deleted_counts['failed_by_overflow'] += 1
                    logger.debug(f"Deleted old failed notification {task_id[:20]}... (overflow protection)")
                except Exception as e:
                    logger.debug(f"Error deleting failed task {task_id}: {e}")

            if deleted_counts['failed_by_overflow'] > 0:
                logger.info(f"Overflow protection: deleted {deleted_counts['failed_by_overflow']} oldest failed notifications")

        # Step 3: Clean up old retry attempts using task manager
        task_manager = _get_task_manager()
        if task_manager:
            deleted_counts['retry_attempts'] = task_manager.cleanup_old_retry_attempts(cutoff_time)
            if deleted_counts['retry_attempts'] > 0:
                logger.info(f"Cleaned up {deleted_counts['retry_attempts']} old retry attempt files (older than {max_age_days} days)")

        total_deleted = deleted_counts['failed_by_overflow'] + deleted_counts['retry_attempts']

        if total_deleted > 0:
            logger.info(f"Cleanup completed - "
                       f"failed_by_overflow: {deleted_counts['failed_by_overflow']}, "
                       f"retry_attempts: {deleted_counts['retry_attempts']}, "
                       f"total: {total_deleted}")

        # Return total count for backward compatibility (tests expect int)
        # Detailed breakdown is logged above
        return total_deleted

    except Exception as e:
        logger.error(f"Error during cleanup_old_failed_notifications: {e}")
        return 0


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

    # Clean up old failed notifications on startup (with overflow protection)
    # Age limit: 30 days, Count limit: 1000 failed notifications max
    logger.info("Running startup cleanup: removing old failed notifications and enforcing limits...")
    cleanup_deleted = cleanup_old_failed_notifications(max_age_days=30, max_failed_count=1000)
    if cleanup_deleted > 0:
        logger.info(f"Startup cleanup completed: deleted {cleanup_deleted} items")
    else:
        logger.info("Startup cleanup completed: no old items to delete")

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
