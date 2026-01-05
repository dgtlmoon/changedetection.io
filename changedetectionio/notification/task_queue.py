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
        'results': True,  # Enable result storage for failed notification tracking
        'store_errors': True  # Store error details for debugging
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

    return huey


def get_failed_notifications(limit=100):
    """
    Get list of failed notification tasks from Huey's result store.

    Args:
        limit: Maximum number of failed tasks to return (default: 100)

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

    try:
        # Query Huey's result storage for failed tasks
        # Note: This requires accessing Huey's internal storage
        from huey.storage import PeeweeStorage

        # Get all results and filter for errors
        # Huey stores results with task IDs as keys
        results = huey.storage.result_store.flush()

        for task_id, result in results.items():
            if isinstance(result, Exception):
                # This is a failed task
                # Try to extract notification data from task args
                try:
                    task_data = huey.storage.get(task_id)
                    if task_data:
                        failed_tasks.append({
                            'task_id': task_id,
                            'timestamp': task_data.get('execute_time'),
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
            # Queue it again
            send_notification_task(notification_data)
            logger.info(f"Re-queued failed notification task {task_id}")
            return True
        else:
            logger.error(f"No notification data found for task {task_id}")
            return False

    except Exception as e:
        logger.error(f"Error retrying notification {task_id}: {e}")
        return False


def send_notification_task(n_object_dict):
    """
    Background task to send a notification with automatic retry on failure.

    Retries 3 times with 60 second delay between attempts.

    IMPORTANT: Notification configuration (notification_urls, notification_title,
    notification_body, notification_format) is RELOADED from the datastore at
    retry time. This allows operators to fix broken settings (e.g., wrong SMTP
    server) and retry with corrected configuration.

    Snapshot data (diff, watch_url, triggered_text, etc.) is preserved from
    the original notification trigger.

    Preserves all logic from the original notification_runner including:
    - Reloading notification settings from current datastore state at retry time
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
        # ALWAYS reload notification configuration from current datastore state
        # This allows operators to fix broken notification settings (e.g., wrong SMTP server)
        # and retry failed notifications with the corrected configuration
        watch_uuid = n_object.get('uuid')
        watch = None

        # Get current watch data if this is a watch notification (not a test notification)
        if watch_uuid and watch_uuid in datastore.data['watching']:
            watch = datastore.data['watching'][watch_uuid]

        # Reload notification_urls from current settings (watch-level or system-level)
        if watch and watch.get('notification_urls'):
            n_object['notification_urls'] = watch.get('notification_urls')
        else:
            # Fallback to system-level notification_urls
            n_object['notification_urls'] = datastore.data['settings']['application'].get('notification_urls', {})

        # Reload notification_title from current settings
        if watch and watch.get('notification_title'):
            n_object['notification_title'] = watch.get('notification_title')
        else:
            n_object['notification_title'] = datastore.data['settings']['application'].get('notification_title')

        # Reload notification_body from current settings
        if watch and watch.get('notification_body'):
            n_object['notification_body'] = watch.get('notification_body')
        else:
            n_object['notification_body'] = datastore.data['settings']['application'].get('notification_body')

        # Reload notification_format from current settings
        if watch and watch.get('notification_format'):
            n_object['notification_format'] = watch.get('notification_format')
        else:
            n_object['notification_format'] = datastore.data['settings']['application'].get('notification_format')

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

    # Apply Huey task decorator
    send_notification_task = huey.task(retries=3, retry_delay=60)(send_notification_task)


def start_huey_consumer(workers=1):
    """
    Start Huey consumer in-process as background threads.

    Replaces the old notification_runner() thread with Huey's consumer
    threads that provide retry logic and persistent queuing.

    Args:
        workers: Number of worker threads (default: 1)
    """
    global huey

    if huey is None:
        raise RuntimeError("Huey not initialized! Call init_huey(datastore_path) first")

    logger.info(f"Starting Huey notification consumer with {workers} worker threads")

    try:
        from huey.consumer import Consumer

        # Create and run consumer
        # Note: We disable signal handlers since we're running in a background thread, not main thread
        consumer = Consumer(
            huey,
            workers=workers,
            worker_type='thread',
            scheduler_interval=1,  # Poll queue every 1 second
            check_worker_health=True,
            health_check_interval=60,
            # Disable signal handlers - we're in a thread, not main process
            # The main Flask app will handle shutdown signals
        )

        # Override signal handler setup to do nothing (we're in a thread)
        consumer._set_signal_handlers = lambda: None

        consumer.run()  # This blocks, so it runs in the thread

    except Exception as e:
        logger.error(f"Failed to start Huey consumer: {e}")
        raise
