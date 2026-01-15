"""
Task data storage management for Huey notifications.

Provides polymorphic storage for retry attempt audit trails and delivered
notification confirmations that persist independently of the Huey queue backend.

This module uses the Strategy pattern to handle different storage backends
(FileStorage, SQLiteStorage, RedisStorage) without conditional logic in the main code.
"""

from .base import HueyTaskDataStorageManager
from .file_storage import FileTaskDataStorageManager
from .sqlite_storage import SqliteTaskDataStorageManager
from .redis_storage import RedisTaskDataStorageManager

__all__ = [
    'HueyTaskDataStorageManager',
    'FileTaskDataStorageManager',
    'SqliteTaskDataStorageManager',
    'RedisTaskDataStorageManager',
    'create_task_data_storage_manager',
]


def create_task_data_storage_manager(huey_storage, fallback_path=None):
    """
    Factory function to create the appropriate task data storage manager.

    Uses duck typing to detect storage backend type and return the appropriate manager.

    Args:
        huey_storage: Huey storage instance (FileStorage, SQLiteStorage, or RedisStorage)
        fallback_path: Fallback path for Redis storage (typically global datastore path)

    Returns:
        HueyTaskDataStorageManager: Appropriate manager for the storage backend

    Raises:
        ValueError: If storage type cannot be determined
    """
    if huey_storage is None:
        raise ValueError("huey_storage cannot be None")

    # Detect storage type using duck typing (check for distinguishing attributes)

    # FileStorage: has 'path' attribute
    if hasattr(huey_storage, 'path') and huey_storage.path is not None:
        from loguru import logger
        logger.debug(f"Detected FileStorage backend")
        return FileTaskDataStorageManager(huey_storage)

    # SQLiteStorage: has 'filename' attribute (path to .db file)
    if hasattr(huey_storage, 'filename') and huey_storage.filename is not None:
        from loguru import logger
        logger.debug(f"Detected SQLiteStorage backend")
        return SqliteTaskDataStorageManager(huey_storage)

    # RedisStorage: has 'conn' attribute (Redis connection)
    if hasattr(huey_storage, 'conn'):
        from loguru import logger
        logger.debug(f"Detected RedisStorage backend")
        return RedisTaskDataStorageManager(huey_storage, fallback_path=fallback_path)

    # Unknown storage type
    storage_type = type(huey_storage).__name__
    raise ValueError(f"Unknown Huey storage type: {storage_type}")
