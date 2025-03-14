from abc import ABC, abstractmethod
import json
from loguru import logger

class StorageBase(ABC):
    """Abstract base class for storage backends"""
    
    @abstractmethod
    def __init__(self, datastore_path, include_default_watches=True, version_tag="0.0.0"):
        """Initialize the storage backend
        
        Args:
            datastore_path (str): Path to the datastore
            include_default_watches (bool): Whether to include default watches
            version_tag (str): Version tag
        """
        pass
    
    @abstractmethod
    def load_data(self):
        """Load data from the storage backend
        
        Returns:
            dict: The loaded data
        """
        pass
    
    @abstractmethod
    def save_data(self, data):
        """Save data to the storage backend
        
        Args:
            data (dict): The data to save
        """
        pass
    
    @abstractmethod
    def save_history_text(self, watch_uuid, contents, timestamp, snapshot_id):
        """Save history text to the storage backend
        
        Args:
            watch_uuid (str): Watch UUID
            contents (str): Contents to save
            timestamp (int): Timestamp
            snapshot_id (str): Snapshot ID
            
        Returns:
            str: Snapshot filename or ID
        """
        pass
    
    @abstractmethod
    def get_history_snapshot(self, watch_uuid, timestamp):
        """Get a history snapshot from the storage backend
        
        Args:
            watch_uuid (str): Watch UUID
            timestamp (int): Timestamp
            
        Returns:
            str: The snapshot content
        """
        pass
    
    @abstractmethod
    def get_history(self, watch_uuid):
        """Get history for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            
        Returns:
            dict: The history with timestamp keys and snapshot IDs as values
        """
        pass
    
    @abstractmethod
    def save_screenshot(self, watch_uuid, screenshot, as_error=False):
        """Save a screenshot for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            screenshot (bytes): Screenshot data
            as_error (bool): Whether this is an error screenshot
        """
        pass
    
    @abstractmethod
    def get_screenshot(self, watch_uuid, is_error=False):
        """Get a screenshot for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            is_error (bool): Whether to get the error screenshot
            
        Returns:
            str or None: The screenshot path or None if not available
        """
        pass
    
    @abstractmethod
    def save_error_text(self, watch_uuid, contents):
        """Save error text for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            contents (str): Error contents
        """
        pass
    
    @abstractmethod
    def get_error_text(self, watch_uuid):
        """Get error text for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            
        Returns:
            str or False: The error text or False if not available
        """
        pass
    
    @abstractmethod
    def save_xpath_data(self, watch_uuid, data, as_error=False):
        """Save XPath data for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            data (dict): XPath data
            as_error (bool): Whether this is error data
        """
        pass
    
    @abstractmethod
    def get_xpath_data(self, watch_uuid, is_error=False):
        """Get XPath data for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            is_error (bool): Whether to get error data
            
        Returns:
            dict or None: The XPath data or None if not available
        """
        pass
    
    @abstractmethod
    def save_last_fetched_html(self, watch_uuid, timestamp, contents):
        """Save last fetched HTML for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            timestamp (int): Timestamp
            contents (str): HTML contents
        """
        pass
    
    @abstractmethod
    def get_fetched_html(self, watch_uuid, timestamp):
        """Get fetched HTML for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            timestamp (int): Timestamp
            
        Returns:
            str or False: The HTML or False if not available
        """
        pass
    
    @abstractmethod
    def save_last_text_fetched_before_filters(self, watch_uuid, contents):
        """Save the last text fetched before filters
        
        Args:
            watch_uuid (str): Watch UUID
            contents (str): Text contents
        """
        pass
    
    @abstractmethod
    def get_last_fetched_text_before_filters(self, watch_uuid):
        """Get the last text fetched before filters
        
        Args:
            watch_uuid (str): Watch UUID
            
        Returns:
            str: The text
        """
        pass
    
    @abstractmethod
    def ensure_data_dir_exists(self, watch_uuid):
        """Ensure the data directory exists for a watch
        
        Args:
            watch_uuid (str): Watch UUID
        """
        pass
    
    @abstractmethod
    def visualselector_data_is_ready(self, watch_uuid):
        """Check if visual selector data is ready
        
        Args:
            watch_uuid (str): Watch UUID
            
        Returns:
            bool: Whether visual selector data is ready
        """
        pass
    
    @abstractmethod
    def clear_watch_history(self, watch_uuid):
        """Clear history for a watch
        
        Args:
            watch_uuid (str): Watch UUID
        """
        pass
    
    @abstractmethod
    def delete_watch(self, watch_uuid):
        """Delete a watch
        
        Args:
            watch_uuid (str): Watch UUID
        """
        pass