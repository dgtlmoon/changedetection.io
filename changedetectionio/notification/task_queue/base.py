"""
Abstract base class for Huey storage backend task managers.
"""

from abc import ABC, abstractmethod


class HueyTaskManager(ABC):
    """
    Abstract base class for Huey storage backend operations.

    Provides a polymorphic interface for storage-specific operations like:
    - Enumerating results (failed notifications)
    - Deleting results
    - Counting pending notifications
    - Clearing all notifications

    Each storage backend (FileStorage, SqliteStorage, RedisStorage) has its own
    concrete implementation that knows how to interact with that specific storage.
    """

    def __init__(self, storage, storage_path=None):
        """
        Initialize task manager with storage instance.

        Args:
            storage: Huey storage instance
            storage_path: Optional path for file-based storage
        """
        self.storage = storage
        self.storage_path = storage_path

    @abstractmethod
    def enumerate_results(self):
        """
        Enumerate all results from storage.

        Returns:
            dict: {task_id: result_data} for all stored results
        """
        pass

    @abstractmethod
    def delete_result(self, task_id):
        """
        Delete a result from storage.

        Args:
            task_id: Task ID to delete

        Returns:
            bool: True if deleted successfully, False otherwise
        """
        pass

    @abstractmethod
    def count_storage_items(self):
        """
        Count items in storage (queue + schedule).

        Returns:
            tuple: (queue_count, schedule_count)
        """
        pass

    @abstractmethod
    def clear_all_notifications(self):
        """
        Clear all notifications (queue, schedule, results, metadata).

        Returns:
            dict: Counts of cleared items by type
        """
        pass

    @abstractmethod
    def store_task_metadata(self, task_id, metadata):
        """
        Store task metadata for later retrieval.

        Args:
            task_id: Task ID
            metadata: Metadata dictionary to store

        Returns:
            bool: True if stored successfully, False otherwise
        """
        pass

    @abstractmethod
    def get_task_metadata(self, task_id):
        """
        Retrieve task metadata.

        Args:
            task_id: Task ID

        Returns:
            dict: Metadata dictionary or None if not found
        """
        pass

    @abstractmethod
    def delete_task_metadata(self, task_id):
        """
        Delete task metadata.

        Args:
            task_id: Task ID

        Returns:
            bool: True if deleted successfully, False otherwise
        """
        pass

    @abstractmethod
    def cleanup_old_retry_attempts(self, cutoff_time):
        """
        Clean up retry attempt records older than cutoff_time.

        Args:
            cutoff_time: Unix timestamp - delete records older than this

        Returns:
            int: Number of retry attempts deleted
        """
        pass
