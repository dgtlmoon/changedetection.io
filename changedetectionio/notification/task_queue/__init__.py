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


# Global Huey instance and datastore path (initialized later)
huey = None
_datastore_path = None  # For file-based retry attempts/success in all backends


def init_huey(datastore_path):
    """
    Initialize Huey instance with the correct datastore path.

    Must be called after datastore is initialized, using datastore.datastore_path

    Args:
        datastore_path: Path to the datastore directory (from ChangeDetectionStore instance)

    Returns:
        Huey instance configured for the specified storage backend
    """
    global huey, _datastore_path

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
        # Get counts using task manager (polymorphic, backend-agnostic)
        queue_count, schedule_count = _count_storage_items()

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
    import pickle
    import time

    try:
        # Use Huey's built-in methods to get queued and scheduled items
        # These methods return pickled bytes that need to be unpickled

        # Get queued tasks (immediate execution)
        if hasattr(huey.storage, 'enqueued_items'):
            try:
                queued_items = list(huey.storage.enqueued_items(limit=limit))
                for queued_bytes in queued_items:
                    if len(pending) >= limit:
                        break
                    try:
                        message = pickle.loads(queued_bytes)

                        # Skip revoked tasks - check if task is in revoked set
                        task_id = message.id if hasattr(message, 'id') else None
                        if task_id and huey.is_revoked(task_id):
                            logger.debug(f"Skipping revoked task {task_id} in get_pending_notifications")
                            continue

                        if hasattr(message, 'args') and message.args:
                            notification_data = message.args[0]
                            # Get task ID and metadata for timestamp
                            task_id = message.id if hasattr(message, 'id') else None
                            metadata = _get_task_metadata(task_id) if task_id else None
                            queued_timestamp = metadata.get('timestamp') if metadata else None

                            # Format timestamp for display
                            from changedetectionio.notification_service import timestamp_to_localtime
                            queued_at_formatted = timestamp_to_localtime(queued_timestamp) if queued_timestamp else 'Unknown'

                            pending.append({
                                'status': 'queued',
                                'watch_url': notification_data.get('watch_url', 'Unknown'),
                                'watch_uuid': notification_data.get('uuid'),
                                'task_id': task_id,
                                'queued_at': queued_timestamp,
                                'queued_at_formatted': queued_at_formatted,
                            })
                    except Exception as e:
                        logger.debug(f"Error processing queued item: {e}")
                        continue
            except Exception as e:
                logger.debug(f"Error getting queued items: {e}")

        # Get scheduled tasks (retrying)
        if hasattr(huey.storage, 'scheduled_items'):
            try:
                scheduled_items = list(huey.storage.scheduled_items(limit=limit))
                for scheduled_bytes in scheduled_items:
                    if len(pending) >= limit:
                        break
                    try:
                        message = pickle.loads(scheduled_bytes)

                        # Skip revoked tasks - check if task is in revoked set
                        task_id = message.id if hasattr(message, 'id') else None
                        if task_id and huey.is_revoked(task_id):
                            logger.debug(f"Skipping revoked task {task_id} in get_pending_notifications")
                            continue

                        if hasattr(message, 'args') and message.args:
                            notification_data = message.args[0]
                            eta = message.eta if hasattr(message, 'eta') else None
                            # Calculate seconds until retry (eta is a datetime object)
                            import datetime
                            if eta:
                                now = datetime.datetime.now() if eta.tzinfo is None else datetime.datetime.now(datetime.timezone.utc)
                                retry_in_seconds = int((eta - now).total_seconds())

                                # Convert eta to local timezone for display
                                if eta.tzinfo is not None:
                                    local_tz = datetime.datetime.now().astimezone().tzinfo
                                    eta_local = eta.astimezone(local_tz)
                                    eta_formatted = eta_local.strftime('%Y-%m-%d %H:%M:%S %Z')
                                else:
                                    eta_formatted = eta.strftime('%Y-%m-%d %H:%M:%S')
                            else:
                                retry_in_seconds = 0
                                eta_formatted = 'Unknown'

                            # Get task ID for manual retry button
                            task_id = message.id if hasattr(message, 'id') else None

                            # Convert eta to Unix timestamp for JavaScript (with safety check)
                            retry_at_timestamp = None
                            if eta and hasattr(eta, 'timestamp'):
                                try:
                                    # Huey stores ETA as naive datetime in UTC - need to add timezone info
                                    if eta.tzinfo is None:
                                        # Naive datetime - assume it's UTC (Huey's default)
                                        import datetime
                                        eta = eta.replace(tzinfo=datetime.timezone.utc)
                                    retry_at_timestamp = int(eta.timestamp())
                                    logger.debug(f"ETA after timezone fix: {eta}, Timestamp: {retry_at_timestamp}")
                                except Exception as e:
                                    logger.debug(f"Error converting eta to timestamp: {e}")

                            # Get original queued timestamp from metadata
                            metadata = _get_task_metadata(task_id) if task_id else None
                            queued_timestamp = metadata.get('timestamp') if metadata else None

                            # Format timestamp for display
                            from changedetectionio.notification_service import timestamp_to_localtime
                            queued_at_formatted = timestamp_to_localtime(queued_timestamp) if queued_timestamp else 'Unknown'

                            # Get retry count from retry_attempts directory
                            # Retry number represents which retry this is (1st retry, 2nd retry, etc.)
                            # If there are N attempt files, we're currently on retry #N
                            retry_number = 1  # Default to 1 (first retry after initial failure)
                            total_attempts = NOTIFICATION_RETRY_COUNT + 1  # Initial attempt + retries
                            watch_uuid = notification_data.get('uuid')
                            retry_attempts = []
                            notification_urls = []

                            # NOTE: Use "is not None" instead of truthiness check because Huey objects can evaluate to False
                            if watch_uuid and huey is not None and hasattr(huey.storage, 'path'):
                                try:
                                    import os
                                    import glob
                                    from .file_storage import _safe_json_load
                                    attempts_dir = os.path.join(huey.storage.path, 'retry_attempts')
                                    if os.path.exists(attempts_dir):
                                        # Load retry attempt files to get notification_urls and payload
                                        attempt_pattern = os.path.join(attempts_dir, f"{watch_uuid}.*.json")
                                        for attempt_file in sorted(glob.glob(attempt_pattern)):
                                            try:
                                                # Use safe JSON load with corruption handling
                                                attempt_data = _safe_json_load(attempt_file, 'retry_attempts', huey.storage.path)
                                                if attempt_data:
                                                    # Format timestamp for display
                                                    attempt_time = attempt_data.get('timestamp')
                                                    if attempt_time:
                                                        from changedetectionio.notification_service import timestamp_to_localtime
                                                        attempt_data['timestamp_formatted'] = timestamp_to_localtime(attempt_time)
                                                    retry_attempts.append(attempt_data)
                                            except Exception as ae:
                                                logger.debug(f"Unable to load retry attempt file {attempt_file}: {ae}")

                                        if len(retry_attempts) > 0:
                                            # Current retry number = number of attempt files
                                            # (1 file = 1st retry, 2 files = 2nd retry, etc.)
                                            retry_number = len(retry_attempts)
                                            logger.debug(f"Watch {watch_uuid[:8]}: Found {len(retry_attempts)} retry files, currently on retry #{retry_number}/{total_attempts}")

                                            # Extract notification_urls from latest retry attempt
                                            latest_attempt = retry_attempts[-1]
                                            attempt_notification_data = latest_attempt.get('notification_data', {})
                                            if attempt_notification_data:
                                                notification_urls = attempt_notification_data.get('notification_urls', [])
                                        else:
                                            # Directory exists but no files yet - first retry
                                            retry_number = 1
                                            logger.debug(f"Watch {watch_uuid[:8]}: Retry attempts dir exists but empty, first retry (retry #1/{total_attempts})")
                                    else:
                                        # No attempts dir yet - this is first retry (after initial failure)
                                        retry_number = 1
                                        logger.debug(f"Watch {watch_uuid[:8]}: No retry attempts dir, this is first retry (retry #1/{total_attempts})")
                                except Exception as e:
                                    logger.warning(f"Error reading retry attempts for {watch_uuid}: {e}, defaulting to attempt #1")
                                    retry_number = 1  # Fallback to 1 on error

                            pending.append({
                                'status': 'retrying',
                                'watch_url': notification_data.get('watch_url', 'Unknown'),
                                'watch_uuid': notification_data.get('uuid'),
                                'retry_at': eta,
                                'retry_at_formatted': eta_formatted,
                                'retry_at_timestamp': retry_at_timestamp,
                                'retry_in_seconds': retry_in_seconds,
                                'task_id': task_id,
                                'queued_at': queued_timestamp,
                                'queued_at_formatted': queued_at_formatted,
                                'retry_number': retry_number,
                                'total_retries': total_attempts,
                                'retry_attempts': retry_attempts,
                                'notification_urls': notification_urls,
                            })
                    except Exception as e:
                        logger.debug(f"Error processing scheduled item: {e}")
                        continue
            except Exception as e:
                logger.debug(f"Error getting scheduled items: {e}")

    except Exception as e:
        logger.error(f"Error getting pending notifications: {e}", exc_info=True)

    logger.debug(f"get_pending_notifications returning {len(pending)} items")
    return pending


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
    Returns successful deliveries, queued, retrying, and failed notifications.

    Returns list sorted by timestamp (newest first) with structure:
    {
        'id': 'task_id or unique_id',
        'status': 'delivered' | 'queued' | 'retrying' | 'failed',
        'timestamp': unix_timestamp,
        'timestamp_formatted': 'human readable',
        'watch_uuid': 'uuid',
        'watch_url': 'url',
        'watch_title': 'title or truncated url',
        'notification_urls': ['endpoint1', 'endpoint2'],
        'retry_number': 1,  # for retrying status
        'total_retries': 3,  # for retrying status
        'apprise_logs': 'logs text',
        'error': 'error text if failed'
    }
    """
    events = []

    # 1. Get delivered (successful) notifications (up to 100)
    delivered = get_delivered_notifications(limit=limit)
    for success in delivered:
        events.append({
            'id': success.get('task_id') or f"success-{success.get('timestamp', 0)}",
            'status': 'delivered',
            'timestamp': success.get('timestamp'),
            'timestamp_formatted': success.get('timestamp_formatted'),
            'watch_uuid': success.get('watch_uuid'),
            'watch_url': success.get('watch_url'),
            'watch_title': success.get('watch_url', 'Unknown')[:50],
            'notification_urls': success.get('notification_urls', []),
            'apprise_logs': '\n'.join(success.get('apprise_logs', [])) if isinstance(success.get('apprise_logs'), list) else success.get('apprise_logs', ''),
            'payload': success.get('payload'),
            'error': None
        })

    # 2. Get pending/queued notifications
    pending = get_pending_notifications(limit=limit)
    for item in pending:
        status = 'retrying' if item.get('status') == 'retrying' else 'queued'

        # Get apprise logs and payload for this task if available
        apprise_logs = None
        payload = None
        task_id = item.get('task_id')
        if task_id:
            log_data = get_task_apprise_log(task_id)
            if log_data and log_data.get('apprise_log'):
                apprise_logs = log_data.get('apprise_log')
            # Get payload from retry attempts if available
            retry_attempts = item.get('retry_attempts', [])
            if retry_attempts:
                payload = retry_attempts[-1].get('payload')

        events.append({
            'id': task_id,
            'status': status,
            'timestamp': item.get('queued_at'),
            'timestamp_formatted': item.get('queued_at_formatted'),
            'watch_uuid': item.get('watch_uuid'),
            'watch_url': item.get('watch_url'),
            'watch_title': item.get('watch_url', 'Unknown')[:50],
            'notification_urls': item.get('notification_urls', []) if item.get('notification_urls') else [],
            'retry_number': item.get('retry_number'),
            'total_retries': item.get('total_retries'),
            'retry_at': item.get('retry_at_timestamp'),
            'retry_at_formatted': item.get('retry_at_formatted'),
            'apprise_logs': apprise_logs,
            'payload': payload,
            'error': None
        })

    # 3. Get failed notifications (dead letter)
    failed = get_failed_notifications(limit=limit)
    for item in failed:
        # Get apprise logs and payload for failed tasks
        apprise_logs = None
        payload = None
        task_id = item.get('task_id')
        if task_id:
            log_data = get_task_apprise_log(task_id)
            if log_data and log_data.get('apprise_log'):
                apprise_logs = log_data.get('apprise_log')

        # Get payload from retry attempts (has the most recent attempt data)
        retry_attempts = item.get('retry_attempts', [])
        if retry_attempts:
            payload = retry_attempts[-1].get('payload')

        events.append({
            'id': task_id,
            'status': 'failed',
            'timestamp': item.get('timestamp'),
            'timestamp_formatted': item.get('timestamp_formatted'),
            'watch_uuid': item.get('notification_data', {}).get('uuid'),
            'watch_url': item.get('notification_data', {}).get('watch_url'),
            'watch_title': item.get('notification_data', {}).get('watch_url', 'Unknown')[:50],
            'notification_urls': item.get('notification_data', {}).get('notification_urls', []),
            'apprise_logs': apprise_logs,
            'payload': payload,
            'error': item.get('error')
        })

    # Sort by timestamp (newest first)
    events.sort(key=lambda x: x.get('timestamp', 0) or 0, reverse=True)

    # HTML escape user-controlled fields to prevent XSS in UI
    from changedetectionio.jinja2_custom.safe_jinja import render_fully_escaped
    for event in events:
        # Escape apprise logs
        if event.get('apprise_logs'):
            event['apprise_logs'] = render_fully_escaped(event['apprise_logs'])

        # Escape error messages
        if event.get('error'):
            event['error'] = render_fully_escaped(event['error'])

        # Escape payload fields (notification title, body, format)
        if event.get('payload') and isinstance(event['payload'], dict):
            if event['payload'].get('notification_title'):
                event['payload']['notification_title'] = render_fully_escaped(event['payload']['notification_title'])
            if event['payload'].get('notification_body'):
                event['payload']['notification_body'] = render_fully_escaped(event['payload']['notification_body'])
            if event['payload'].get('notification_format'):
                event['payload']['notification_format'] = render_fully_escaped(event['payload']['notification_format'])

    # Limit results
    return events[:limit]


def _cleanup_old_success_notifications(success_dir, keep=50):
    """
    Clean up old success notification files, keeping only the newest 'keep' files.

    This is called after each successful notification to maintain a manageable number of files.
    Can also be called on startup to clean up old files.

    Args:
        success_dir: Directory containing success-*.json files
        keep: Number of newest files to keep (default: 50)
    """
    try:
        import os
        if not os.path.exists(success_dir):
            return

        # Get all success-*.json files
        success_files = [f for f in os.listdir(success_dir) if f.startswith('success-') and f.endswith('.json')]

        # If we're under the limit, no cleanup needed
        if len(success_files) <= keep:
            return

        # Sort by modification time (oldest first for deletion)
        success_files.sort(key=lambda f: os.path.getmtime(os.path.join(success_dir, f)))

        # Delete oldest files beyond the keep limit
        files_to_delete = success_files[:-keep]  # All but the newest 'keep' files
        for filename in files_to_delete:
            try:
                os.remove(os.path.join(success_dir, filename))
            except Exception as e:
                logger.debug(f"Error deleting old success file {filename}: {e}")

        if files_to_delete:
            logger.debug(f"Cleaned up {len(files_to_delete)} old success notification files (keeping {keep} newest)")
    except Exception as e:
        logger.debug(f"Error cleaning up old success notifications: {e}")


def get_delivered_notifications(limit=50):
    """
    Get list of delivered (successful) notifications by scanning the success directory.

    Each successful notification is stored as an individual file:
    {storage_path}/success/success-{task_id}.json

    Args:
        limit: Maximum number to return (default: 50)

    Returns:
        List of dicts with delivered notification info (newest first)
    """
    if huey is None:
        return []

    storage_path = getattr(huey.storage, 'path', None)
    if not storage_path:
        return []

    import os

    try:
        success_dir = os.path.join(storage_path, 'success')

        if not os.path.exists(success_dir):
            return []

        # Get all success-*.json files
        success_files = [f for f in os.listdir(success_dir) if f.startswith('success-') and f.endswith('.json')]

        # Sort by modification time (newest first)
        success_files.sort(key=lambda f: os.path.getmtime(os.path.join(success_dir, f)), reverse=True)

        # Load up to 'limit' files
        notifications = []
        from changedetectionio.notification_service import timestamp_to_localtime
        from .file_storage import _safe_json_load

        for filename in success_files[:limit]:
            try:
                file_path = os.path.join(success_dir, filename)
                # Use safe JSON load with corruption handling
                notif = _safe_json_load(file_path, 'success', storage_path)
                if notif:
                    if notif.get('timestamp'):
                        notif['timestamp_formatted'] = timestamp_to_localtime(notif['timestamp'])
                    notifications.append(notif)
            except Exception as e:
                logger.debug(f"Error reading {filename}: {e}")
                continue

        return notifications

    except Exception as e:
        logger.debug(f"Unable to load delivered notifications: {e}")

    return []


def get_last_successful_notification():
    """
    Get the most recent successful notification for reference.

    Returns:
        Dict with success info or None if no successful notifications yet
    """
    delivered = get_delivered_notifications(limit=1)
    return delivered[0] if delivered else None


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
        # Query Huey's result storage for failed tasks using backend-agnostic helper
        cutoff_time = time.time() - (max_age_days * 86400)

        # Use helper function that works with all storage backends
        results = _enumerate_results()

        # Import Huey's Error class for checking failed tasks
        from huey.utils import Error as HueyError

        for task_id, result in results.items():
            if isinstance(result, (Exception, HueyError)):
                # This is a failed task (either Exception or Huey Error object)
                # Check if task is still scheduled for retry
                # If it is, don't include it in failed list (still retrying)
                if huey.storage:
                    try:
                        # Check if this task is in the schedule queue (still being retried)
                        task_still_scheduled = False

                        # Use Huey's built-in scheduled_items() method to get scheduled tasks
                        try:
                            if hasattr(huey.storage, 'scheduled_items'):
                                import pickle
                                scheduled_items = list(huey.storage.scheduled_items())
                                for scheduled_bytes in scheduled_items:
                                    try:
                                        # scheduled_items() returns pickled bytes, need to unpickle
                                        scheduled_message = pickle.loads(scheduled_bytes)
                                        # Each item is a Message object with an 'id' attribute
                                        if hasattr(scheduled_message, 'id'):
                                            scheduled_task_id = scheduled_message.id
                                            if scheduled_task_id == task_id:
                                                task_still_scheduled = True
                                                logger.debug(f"Task {task_id[:20]}... IS scheduled")
                                                break
                                    except Exception as e:
                                        logger.debug(f"Error checking scheduled message: {e}")
                                        continue
                        except Exception as se:
                            logger.debug(f"Error checking schedule: {se}")

                        # Also check if task failed very recently (within last 5 seconds)
                        # Handles race condition where result is written before retry is scheduled
                        if not task_still_scheduled:
                            task_metadata = _get_task_metadata(task_id)
                            if task_metadata:
                                task_time = task_metadata.get('timestamp', 0)
                                time_since_failure = time.time() - task_time if task_time else 999

                                # If task failed very recently (< 5 seconds ago), it might still be scheduling a retry
                                # Be conservative and don't count it as permanently failed yet
                                if time_since_failure < 5:
                                    logger.debug(f"Task {task_id[:20]}... failed only {time_since_failure:.1f}s ago, might still be scheduling retry")
                                    task_still_scheduled = True  # Treat as potentially still retrying

                        # Skip this task if it's still scheduled for retry
                        if task_still_scheduled:
                            logger.debug(f"Task {task_id[:20]}... still scheduled for retry, not counting as failed yet")
                            continue
                        else:
                            logger.debug(f"Task {task_id[:20]}... NOT in schedule, counting as failed")
                    except Exception as e:
                        logger.debug(f"Error checking schedule for task {task_id}: {e}")

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
                            import glob
                            from .file_storage import _safe_json_load

                            attempts_dir = os.path.join(huey.storage.path, 'retry_attempts')
                            if os.path.exists(attempts_dir):
                                attempt_pattern = os.path.join(attempts_dir, f"{notification_watch_uuid}.*.json")
                                for attempt_file in sorted(glob.glob(attempt_pattern)):
                                    try:
                                        # Use safe JSON load with corruption handling
                                        attempt_data = _safe_json_load(attempt_file, 'retry_attempts', huey.storage.path)
                                        if attempt_data:
                                            # Format timestamp for display
                                            attempt_time = attempt_data.get('timestamp')
                                            if attempt_time:
                                                attempt_data['timestamp_formatted'] = timestamp_to_localtime(attempt_time)
                                            retry_attempts.append(attempt_data)
                                    except Exception as ae:
                                        logger.debug(f"Unable to load retry attempt file {attempt_file}: {ae}")

                        # Merge notification_data from latest retry attempt (has reloaded notification_urls)
                        if retry_attempts:
                            latest_attempt = retry_attempts[-1]
                            attempt_notification_data = latest_attempt.get('notification_data', {})
                            if attempt_notification_data:
                                notification_data.update(attempt_notification_data)

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

    Returns dict with:
        - apprise_log: str (the log text)
        - task_id: str
        - watch_url: str (if available)
        - notification_urls: list (if available)
        - error: str (if failed)
    """
    if huey is None:
        return None

    try:
        # First check task metadata for notification data and logs
        metadata = _get_task_metadata(task_id)

        # Also check Huey result for error info (failed tasks)
        from huey.utils import Error as HueyError
        error_info = None
        try:
            result = huey.result(task_id, preserve=True)
            if result and isinstance(result, (Exception, HueyError)):
                error_info = str(result)
        except Exception as e:
            # If huey.result() raises an exception, that IS the error we want
            # (Huey raises the stored exception when calling result() on failed tasks)
            error_info = str(e)
            logger.debug(f"Got error from result for task {task_id}: {type(e).__name__}")

        if metadata:
            # Get apprise logs from metadata (could be 'apprise_logs' list or 'apprise_log' string)
            apprise_logs = metadata.get('apprise_logs', [])
            apprise_log_text = '\n'.join(apprise_logs) if isinstance(apprise_logs, list) else metadata.get('apprise_log', '')

            # If no logs in metadata but we have error_info, try to extract from error
            if not apprise_log_text and error_info and 'Apprise logs:' in error_info:
                parts = error_info.split('Apprise logs:', 1)
                if len(parts) > 1:
                    apprise_log_text = parts[1].strip()
                    # The exception string has escaped newlines (\n), convert to actual newlines
                    apprise_log_text = apprise_log_text.replace('\\n', '\n')
                    # Also remove trailing quotes and closing parens from exception repr
                    apprise_log_text = apprise_log_text.rstrip("')")
                    logger.debug(f"Extracted Apprise logs from error for task {task_id}: {len(apprise_log_text)} chars")

                # Clean up error to not duplicate the Apprise logs
                # Only show the main error message, not the logs again
                error_parts = error_info.split('\nApprise logs:', 1)
                if len(error_parts) > 1:
                    error_info = error_parts[0]  # Keep only the main error message

            # Use metadata for apprise_log and notification data, but also include error from result
            result = {
                'task_id': task_id,
                'apprise_log': apprise_log_text if apprise_log_text else 'No log available',
                'watch_url': metadata.get('notification_data', {}).get('watch_url'),
                'notification_urls': metadata.get('notification_data', {}).get('notification_urls', []),
                'error': error_info if error_info else metadata.get('error'),
                'timestamp': metadata.get('timestamp')
            }
            logger.debug(f"Returning log data for task {task_id}: apprise_log length={len(result['apprise_log'])}, has_error={bool(result['error'])}")
            return result

        # If not in metadata, try to extract from result only
        if error_info:
            # Try to extract Apprise log from error message
            apprise_log = 'No detailed log available'
            if 'Apprise logs:' in error_info:
                parts = error_info.split('Apprise logs:', 1)
                if len(parts) > 1:
                    apprise_log = parts[1].strip()

            return {
                'task_id': task_id,
                'apprise_log': apprise_log,
                'error': error_info
            }

        return None

    except Exception as e:
        logger.error(f"Error getting Apprise log for task {task_id}: {e}")
        return None


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
    if huey is None:
        logger.error("Huey not initialized")
        return False

    try:
        # First, check if task is actually scheduled
        scheduled_items = list(huey.storage.scheduled_items())
        task_found = False
        notification_data = None

        import pickle
        for scheduled_bytes in scheduled_items:
            try:
                message = pickle.loads(scheduled_bytes)
                if hasattr(message, 'id') and message.id == task_id:
                    task_found = True
                    # Extract notification data from scheduled task
                    if hasattr(message, 'args') and message.args:
                        notification_data = message.args[0]
                    break
            except Exception as e:
                logger.debug(f"Error checking scheduled task: {e}")
                continue

        if not task_found:
            logger.error(f"Task {task_id} not found in schedule")
            return False

        if not notification_data:
            logger.error(f"No notification data found for task {task_id}")
            return False

        # Execute the notification NOW (synchronously, not queued) by calling the task function directly
        logger.info(f"Executing notification for task {task_id} immediately (not queued)...")

        # CRITICAL: Revoke the scheduled task FIRST to prevent race condition
        # where the consumer picks it up while we're executing it
        huey.revoke_by_id(task_id, revoke_once=True)
        logger.info(f"Revoked scheduled task {task_id} before execution (prevents automatic retry)")

        try:
            # Import here to avoid circular dependency
            from changedetectionio.flask_app import datastore
            from changedetectionio.notification.handler import process_notification
            from changedetectionio.notification_service import NotificationContextData

            # Wrap dict in NotificationContextData if needed
            if not isinstance(notification_data, NotificationContextData):
                notification_data = NotificationContextData(notification_data)

            # Call the notification processing function directly (not via Huey queue)
            # This executes synchronously in the current thread
            sent_obj = process_notification(notification_data, datastore)

            # If we get here, notification was sent successfully!
            logger.info(f"✓ Notification sent successfully for task {task_id}")

            # Clean up old metadata and result
            _delete_result(task_id)
            _delete_task_metadata(task_id)
            logger.info(f"Cleaned up old result/metadata for task {task_id}")

            return True

        except Exception as e:
            # Notification failed - re-queue it so it doesn't disappear and can retry automatically
            logger.warning(f"Failed to send notification for task {task_id}: {e}")
            logger.info(f"Re-queueing notification for automatic retry after manual send failed")

            # Re-queue the notification for automatic retry with exponential backoff
            # This ensures it doesn't disappear from the dashboard and will retry later
            try:
                result = send_notification_task(notification_data)
                logger.info(f"Re-queued notification after failed manual send")
            except Exception as queue_error:
                logger.error(f"Failed to re-queue notification: {queue_error}")

            return False

    except Exception as e:
        logger.error(f"Error executing scheduled notification {task_id}: {e}")
        return False


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

            # Remove from dead letter queue using backend-appropriate method
            _delete_result(task_id)

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

        # Use helper function to get all results from backend-agnostic storage
        # This works with FileStorage (default), SqliteStorage, and RedisStorage
        results = _enumerate_results()

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



def _reload_notification_config(n_object, watch, datastore):
    """
    Reload notification_urls and notification_format with cascading priority.

    Priority: Watch settings > Tag settings > Global settings

    This is done on every send/retry to allow operators to fix broken
    notification settings and retry with corrected configuration.
    """
    n_object['notification_urls'] = _check_cascading_vars(datastore, 'notification_urls', watch)
    n_object['notification_format'] = _check_cascading_vars(datastore, 'notification_format', watch)

    if not n_object.get('notification_urls'):
        raise Exception("No notification_urls defined after checking cascading (Watch > Tag > System)")


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


def _get_storage_path():
    """Get Huey storage path if available."""
    if huey is None:
        return None
    storage_path = getattr(huey.storage, 'path', None)
    if storage_path:
        logger.debug(f"Storage type: {type(huey.storage).__name__}, path: {storage_path}")
    return storage_path


def _cleanup_retry_attempts(watch_uuid, storage_path):
    """Delete all retry attempt files for a watch after successful send."""
    import os
    import glob

    if not watch_uuid or not storage_path:
        return

    attempts_dir = os.path.join(storage_path, 'retry_attempts')
    if not os.path.exists(attempts_dir):
        return

    attempt_pattern = os.path.join(attempts_dir, f"{watch_uuid}.*.json")
    for attempt_file in glob.glob(attempt_pattern):
        os.remove(attempt_file)
    logger.debug(f"Cleaned up retry attempt files for successful watch {watch_uuid}")


def _extract_notification_urls(n_object):
    """Extract notification URLs from n_object (handles dict or list)."""
    notif_urls = n_object.get('notification_urls', [])
    if isinstance(notif_urls, dict):
        return list(notif_urls.keys())
    elif isinstance(notif_urls, list):
        return notif_urls
    return []


def _store_successful_notification(n_object, apprise_logs, payload=None):
    """Store successful notification record and cleanup retry attempts (with atomic write)."""
    import os
    import time

    storage_path = _get_storage_path()
    if not storage_path:
        return

    watch_uuid = n_object.get('uuid')

    # Cleanup retry attempts
    _cleanup_retry_attempts(watch_uuid, storage_path)

    # Store success record
    success_dir = os.path.join(storage_path, 'success')
    os.makedirs(success_dir, exist_ok=True)

    timestamp = time.time()
    unique_id = f"delivered-{watch_uuid}-{int(timestamp * 1000)}"

    success_data = {
        'task_id': unique_id,
        'timestamp': timestamp,
        'watch_url': n_object.get('watch_url'),
        'watch_uuid': watch_uuid,
        'notification_urls': _extract_notification_urls(n_object),
        'apprise_logs': apprise_logs if apprise_logs else [],
        'payload': payload  # What was actually sent to Apprise
    }

    success_file = os.path.join(success_dir, f"success-{unique_id}.json")

    # Use atomic write to prevent corruption on crash
    from .file_storage import _atomic_json_write
    try:
        _atomic_json_write(success_file, success_data)
        logger.debug(f"Stored delivered notification: {unique_id}")
    except Exception as e:
        logger.error(f"Failed to store successful notification atomically: {e}")

    # Cleanup old success files
    _cleanup_old_success_notifications(success_dir, keep=50)


def _store_retry_attempt(n_object, error, payload=None):
    """Store retry attempt details after failure (with atomic write)."""
    import os
    import time
    import uuid

    if huey is None or not hasattr(huey.storage, 'path'):
        return

    attempts_dir = os.path.join(huey.storage.path, 'retry_attempts')
    os.makedirs(attempts_dir, exist_ok=True)

    watch_uuid = n_object.get('uuid', str(uuid.uuid4()))

    # Count existing attempts
    attempt_files = [f for f in os.listdir(attempts_dir) if f.startswith(f"{watch_uuid}.")]
    attempt_number = len(attempt_files) + 1

    # Cleanup stale attempts (>5 minutes old)
    if attempt_files:
        oldest_file = min(attempt_files, key=lambda f: os.path.getmtime(os.path.join(attempts_dir, f)))
        oldest_time = os.path.getmtime(os.path.join(attempts_dir, oldest_file))
        if time.time() - oldest_time > 300:  # 5 minutes
            logger.debug(f"Cleaning up {len(attempt_files)} stale retry files for {watch_uuid}")
            for old_file in attempt_files:
                try:
                    os.remove(os.path.join(attempts_dir, old_file))
                except:
                    pass
            attempt_number = 1

    # Store attempt
    timestamp = int(time.time())
    attempt_file = os.path.join(attempts_dir, f"{watch_uuid}.{attempt_number}.{timestamp}.json")

    attempt_data = {
        'watch_uuid': watch_uuid,
        'attempt_number': attempt_number,
        'timestamp': time.time(),
        'watch_url': n_object.get('watch_url'),
        'error': str(error),
        'will_retry': attempt_number <= NOTIFICATION_RETRY_COUNT,
        'notification_data': n_object,  # Full notification context for verification
        'payload': payload  # What was attempted to be sent to Apprise
    }

    # Use atomic write to prevent corruption on crash
    from .file_storage import _atomic_json_write
    try:
        _atomic_json_write(attempt_file, attempt_data)
        logger.debug(f"Stored retry attempt {attempt_number} for watch {watch_uuid}")
    except Exception as e:
        logger.error(f"Failed to store retry attempt atomically: {e}")


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
