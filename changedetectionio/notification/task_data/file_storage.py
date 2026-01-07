"""
FileStorage backend task data manager for Huey notifications.

For local file-based storage (the default Huey backend).
"""

from loguru import logger
from .base import HueyTaskDataStorageManager


class FileTaskDataStorageManager(HueyTaskDataStorageManager):
    """Task data manager for FileStorage backend (local file-based storage)."""

    @property
    def storage_path(self):
        """
        Get storage path from FileStorage's 'path' attribute.

        FileStorage stores everything under a single directory specified by the 'path' attribute.

        Returns:
            str: Storage path, or None if unavailable
        """
        # Use explicit path if provided (for testing)
        if self._explicit_storage_path:
            return self._explicit_storage_path

        # FileStorage has a 'path' attribute pointing to its directory
        storage_path = getattr(self.storage, 'path', None)

        if storage_path:
            logger.debug(f"FileStorage path: {storage_path}")
        else:
            logger.warning("FileStorage has no 'path' attribute")

        return storage_path
