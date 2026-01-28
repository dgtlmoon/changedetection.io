"""
Base classes for the datastore.

This module defines the abstract interfaces that all datastore implementations must follow.
"""

from abc import ABC, abstractmethod
from threading import Lock
from loguru import logger


class DataStore(ABC):
    """
    Abstract base class for all datastore implementations.

    Defines the core interface that all datastores must implement for:
    - Loading and saving data
    - Managing watches
    - Handling settings
    - Providing data access
    """

    lock = Lock()
    datastore_path = None

    @abstractmethod
    def reload_state(self, datastore_path, include_default_watches, version_tag):
        """
        Load data from persistent storage.

        Args:
            datastore_path: Path to the datastore directory
            include_default_watches: Whether to create default watches if none exist
            version_tag: Application version string
        """
        pass

    @abstractmethod
    def add_watch(self, url, **kwargs):
        """
        Add a new watch.

        Args:
            url: URL to watch
            **kwargs: Additional watch parameters

        Returns:
            UUID of the created watch
        """
        pass

    @abstractmethod
    def update_watch(self, uuid, update_obj):
        """
        Update an existing watch.

        Args:
            uuid: Watch UUID
            update_obj: Dictionary of fields to update
        """
        pass

    @abstractmethod
    def delete(self, uuid):
        """
        Delete a watch.

        Args:
            uuid: Watch UUID to delete
        """
        pass

    @property
    @abstractmethod
    def data(self):
        """
        Access to the underlying data structure.

        Returns:
            Dictionary containing all datastore data
        """
        pass

    @abstractmethod
    def force_save_all(self):
        """
        Force immediate synchronous save of all data to storage.

        This is the abstract method for forcing a complete save.
        Different backends implement this differently:
        - File backend: Mark all watches/settings dirty, then save
        - Redis backend: SAVE command or pipeline flush
        - SQL backend: COMMIT transaction

        Used by:
        - Backup creation (ensure everything is saved before backup)
        - Shutdown (ensure all changes are persisted)
        - Manual save operations
        """
        pass
