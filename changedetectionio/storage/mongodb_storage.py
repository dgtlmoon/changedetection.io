import os
from copy import deepcopy

import brotli
import zlib
import json
import time
from loguru import logger
from pymongo import MongoClient
from urllib.parse import urlparse
import base64

from .storage_base import StorageBase

class MongoDBStorage(StorageBase):
    """MongoDB storage backend"""
    
    def __init__(self, datastore_path, include_default_watches=True, version_tag="0.0.0"):
        """Initialize the MongoDB storage backend
        
        Args:
            datastore_path (str): MongoDB connection URI
            include_default_watches (bool): Whether to include default watches
            version_tag (str): Version tag
        """
        # Parse MongoDB URI from datastore_path
        parsed_uri = urlparse(datastore_path)
        self.db_name = parsed_uri.path.lstrip('/')
        if not self.db_name:
            self.db_name = 'changedetection'
            
        # Connect to MongoDB
        self.client = MongoClient(datastore_path)
        self.db = self.client[self.db_name]
        
        # Collections
        self.app_collection = self.db['app']
        self.watches_collection = self.db['watches']
        self.snapshots_collection = self.db['snapshots']
        self.history_collection = self.db['history']
        self.error_collection = self.db['errors']
        self.xpath_collection = self.db['xpath']
        self.html_collection = self.db['html']
        
        logger.info(f"MongoDB storage initialized, connected to {datastore_path}")
    
    def load_data(self):
        """Load data from MongoDB
        
        Returns:
            dict: The loaded data
        """
        app_data = self.app_collection.find_one({'_id': 'app_data'})
        if not app_data:
            return None
            
        # Remove MongoDB _id field
        if '_id' in app_data:
            del app_data['_id']
            
        return app_data
    
    def save_data(self, data):
        """Save data to MongoDB
        
        Args:
            data (dict): The data to save
        """
        try:
            # Create a copy to modify
            data_copy = deepcopy(data)
            
            # Set _id for app data
            data_copy['_id'] = 'app_data'
            
            # Insert or update app data
            self.app_collection.replace_one({'_id': 'app_data'}, data_copy, upsert=True)
            
            # Also store watches separately for more granular access
            # This provides a safety net in case of corrupted app_data
            watches = data.get('watching', {})
            for uuid, watch in watches.items():
                if isinstance(watch, dict):  # Handle case where watch is a Watch object
                    watch_copy = deepcopy(dict(watch))
                else:
                    watch_copy = deepcopy(watch)
                watch_copy['_id'] = uuid
                self.watches_collection.replace_one({'_id': uuid}, watch_copy, upsert=True)
                
            # Also store tags separately
            if 'settings' in data and 'application' in data['settings'] and 'tags' in data['settings']['application']:
                tags = data['settings']['application']['tags']
                for uuid, tag in tags.items():
                    if isinstance(tag, dict):  # Handle case where tag is a Tag object
                        tag_copy = deepcopy(dict(tag))
                    else:
                        tag_copy = deepcopy(tag)
                    tag_copy['_id'] = uuid
                    self.db['tags'].replace_one({'_id': uuid}, tag_copy, upsert=True)
                    
        except Exception as e:
            logger.error(f"Error writing to MongoDB: {str(e)}")
            raise e
    
    def ensure_data_dir_exists(self, watch_uuid):
        """Ensure the data directory exists for a watch
        
        Args:
            watch_uuid (str): Watch UUID
        """
        # MongoDB doesn't need directories, this is a no-op
        pass
    
    def save_history_text(self, watch_uuid, contents, timestamp, snapshot_id):
        """Save history text to MongoDB
        
        Args:
            watch_uuid (str): Watch UUID
            contents (str): Contents to save
            timestamp (int): Timestamp
            snapshot_id (str): Snapshot ID
            
        Returns:
            str: Snapshot ID
        """
        # Compress the contents
        compressed_contents = brotli.compress(contents.encode('utf-8'), mode=brotli.MODE_TEXT)
        
        # Store the snapshot
        snapshot_data = {
            '_id': f"{watch_uuid}:{timestamp}",
            'watch_uuid': watch_uuid,
            'timestamp': timestamp,
            'snapshot_id': snapshot_id,
            'contents': base64.b64encode(compressed_contents).decode('ascii'),
            'compressed': True
        }
        
        self.snapshots_collection.replace_one({'_id': snapshot_data['_id']}, snapshot_data, upsert=True)
        
        # Update history index
        history_entry = {
            'watch_uuid': watch_uuid,
            'timestamp': timestamp,
            'snapshot_id': snapshot_id
        }
        
        self.history_collection.replace_one(
            {'watch_uuid': watch_uuid, 'timestamp': timestamp},
            history_entry, 
            upsert=True
        )
        
        return snapshot_id
    
    def get_history(self, watch_uuid):
        """Get history for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            
        Returns:
            dict: The history with timestamp keys and snapshot IDs as values
        """
        history = {}
        
        # Query history entries for this watch
        entries = self.history_collection.find({'watch_uuid': watch_uuid}).sort('timestamp', 1)
        
        for entry in entries:
            history[str(entry['timestamp'])] = entry['snapshot_id']
            
        return history
    
    def get_history_snapshot(self, watch_uuid, timestamp):
        """Get a history snapshot from MongoDB
        
        Args:
            watch_uuid (str): Watch UUID
            timestamp (int): Timestamp
            
        Returns:
            str: The snapshot content
        """
        # Query for the snapshot
        snapshot = self.snapshots_collection.find_one({'_id': f"{watch_uuid}:{timestamp}"})
        
        if not snapshot:
            return None
            
        if snapshot.get('compressed', False):
            # Decompress the contents
            compressed_data = base64.b64decode(snapshot['contents'])
            return brotli.decompress(compressed_data).decode('utf-8')
        else:
            return snapshot['contents']
    
    def save_screenshot(self, watch_uuid, screenshot, as_error=False):
        """Save a screenshot for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            screenshot (bytes): Screenshot data
            as_error (bool): Whether this is an error screenshot
        """
        collection_name = 'error_screenshots' if as_error else 'screenshots'
        collection = self.db[collection_name]
        
        # Encode the screenshot as base64
        encoded_screenshot = base64.b64encode(screenshot).decode('ascii')
        
        screenshot_data = {
            '_id': watch_uuid,
            'watch_uuid': watch_uuid,
            'screenshot': encoded_screenshot,
            'timestamp': int(time.time())
        }
        
        collection.replace_one({'_id': watch_uuid}, screenshot_data, upsert=True)
    
    def get_screenshot(self, watch_uuid, is_error=False):
        """Get a screenshot for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            is_error (bool): Whether to get the error screenshot
            
        Returns:
            bytes or None: The screenshot data or None if not available
        """
        collection_name = 'error_screenshots' if is_error else 'screenshots'
        collection = self.db[collection_name]
        
        screenshot_data = collection.find_one({'_id': watch_uuid})
        if not screenshot_data:
            return None
            
        # Decode the screenshot from base64
        return base64.b64decode(screenshot_data['screenshot'])
    
    def save_error_text(self, watch_uuid, contents):
        """Save error text for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            contents (str): Error contents
        """
        error_data = {
            '_id': watch_uuid,
            'watch_uuid': watch_uuid,
            'error_text': contents,
            'timestamp': int(time.time())
        }
        
        self.error_collection.replace_one({'_id': watch_uuid}, error_data, upsert=True)
    
    def get_error_text(self, watch_uuid):
        """Get error text for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            
        Returns:
            str or False: The error text or False if not available
        """
        error_data = self.error_collection.find_one({'_id': watch_uuid})
        if not error_data:
            return False
            
        return error_data['error_text']
    
    def save_xpath_data(self, watch_uuid, data, as_error=False):
        """Save XPath data for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            data (dict): XPath data
            as_error (bool): Whether this is error data
        """
        # Compress the data
        compressed_data = zlib.compress(json.dumps(data).encode())
        
        _id = f"{watch_uuid}:error" if as_error else watch_uuid
        
        xpath_data = {
            '_id': _id,
            'watch_uuid': watch_uuid,
            'is_error': as_error,
            'data': base64.b64encode(compressed_data).decode('ascii'),
            'timestamp': int(time.time())
        }
        
        self.xpath_collection.replace_one({'_id': _id}, xpath_data, upsert=True)
    
    def get_xpath_data(self, watch_uuid, is_error=False):
        """Get XPath data for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            is_error (bool): Whether to get error data
            
        Returns:
            dict or None: The XPath data or None if not available
        """
        _id = f"{watch_uuid}:error" if is_error else watch_uuid
        
        xpath_data = self.xpath_collection.find_one({'_id': _id})
        if not xpath_data:
            return None
            
        # Decompress the data
        compressed_data = base64.b64decode(xpath_data['data'])
        return json.loads(zlib.decompress(compressed_data).decode('utf-8'))
    
    def save_last_fetched_html(self, watch_uuid, timestamp, contents):
        """Save last fetched HTML for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            timestamp (int): Timestamp
            contents (str): HTML contents
        """
        # Compress the contents
        contents_bytes = contents.encode('utf-8') if isinstance(contents, str) else contents
        try:
            compressed_contents = brotli.compress(contents_bytes)
        except Exception as e:
            logger.warning(f"{watch_uuid} - Unable to compress HTML snapshot: {str(e)}")
            compressed_contents = contents_bytes
        
        html_data = {
            '_id': f"{watch_uuid}:{timestamp}",
            'watch_uuid': watch_uuid,
            'timestamp': timestamp,
            'html': base64.b64encode(compressed_contents).decode('ascii'),
            'compressed': True
        }
        
        self.html_collection.replace_one({'_id': html_data['_id']}, html_data, upsert=True)
        
        # Prune old snapshots - keep only the newest 2
        self._prune_last_fetched_html_snapshots(watch_uuid)
    
    def _prune_last_fetched_html_snapshots(self, watch_uuid):
        """Prune old HTML snapshots
        
        Args:
            watch_uuid (str): Watch UUID
        """
        # Get all HTML snapshots for this watch, sorted by timestamp descending
        html_snapshots = list(
            self.html_collection.find({'watch_uuid': watch_uuid}).sort('timestamp', -1)
        )
        
        # Keep only the first 2
        if len(html_snapshots) > 2:
            for snapshot in html_snapshots[2:]:
                self.html_collection.delete_one({'_id': snapshot['_id']})
    
    def get_fetched_html(self, watch_uuid, timestamp):
        """Get fetched HTML for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            timestamp (int): Timestamp
            
        Returns:
            str or False: The HTML or False if not available
        """
        html_data = self.html_collection.find_one({'_id': f"{watch_uuid}:{timestamp}"})
        
        if not html_data:
            return False
            
        if html_data.get('compressed', False):
            # Decompress the contents
            compressed_data = base64.b64decode(html_data['html'])
            return brotli.decompress(compressed_data).decode('utf-8')
        else:
            return html_data['html']
    
    def save_last_text_fetched_before_filters(self, watch_uuid, contents):
        """Save the last text fetched before filters
        
        Args:
            watch_uuid (str): Watch UUID
            contents (str): Text contents
        """
        # Compress the contents
        compressed_contents = brotli.compress(contents.encode('utf-8'), mode=brotli.MODE_TEXT)
        
        last_fetched_data = {
            '_id': watch_uuid,
            'watch_uuid': watch_uuid,
            'contents': base64.b64encode(compressed_contents).decode('ascii'),
            'timestamp': int(time.time())
        }
        
        self.db['last_fetched'].replace_one({'_id': watch_uuid}, last_fetched_data, upsert=True)
    
    def get_last_fetched_text_before_filters(self, watch_uuid):
        """Get the last text fetched before filters
        
        Args:
            watch_uuid (str): Watch UUID
            
        Returns:
            str: The text
        """
        last_fetched_data = self.db['last_fetched'].find_one({'_id': watch_uuid})
        
        if not last_fetched_data:
            # If a previous attempt doesnt yet exist, just snarf the previous snapshot instead
            history = self.get_history(watch_uuid)
            dates = list(history.keys())
            
            if len(dates):
                return self.get_history_snapshot(watch_uuid, dates[-1])
            else:
                return ''
                
        # Decompress the contents
        compressed_data = base64.b64decode(last_fetched_data['contents'])
        return brotli.decompress(compressed_data).decode('utf-8')
    
    def visualselector_data_is_ready(self, watch_uuid):
        """Check if visual selector data is ready
        
        Args:
            watch_uuid (str): Watch UUID
            
        Returns:
            bool: Whether visual selector data is ready
        """
        # Check if screenshot and xpath data exist
        screenshot = self.db['screenshots'].find_one({'_id': watch_uuid})
        xpath_data = self.xpath_collection.find_one({'_id': watch_uuid})
        
        return screenshot is not None and xpath_data is not None
    
    def clear_watch_history(self, watch_uuid):
        """Clear history for a watch
        
        Args:
            watch_uuid (str): Watch UUID
        """
        # Delete all snapshots and history for this watch
        self.snapshots_collection.delete_many({'watch_uuid': watch_uuid})
        self.history_collection.delete_many({'watch_uuid': watch_uuid})
        self.html_collection.delete_many({'watch_uuid': watch_uuid})
        self.db['last_fetched'].delete_many({'watch_uuid': watch_uuid})
        self.xpath_collection.delete_many({'watch_uuid': watch_uuid})
        self.db['screenshots'].delete_many({'watch_uuid': watch_uuid})
        self.error_collection.delete_many({'watch_uuid': watch_uuid})
    
    def delete_watch(self, watch_uuid):
        """Delete a watch
        
        Args:
            watch_uuid (str): Watch UUID
        """
        # Clear all history data
        self.clear_watch_history(watch_uuid)
        
        # Also delete error screenshots
        self.db['error_screenshots'].delete_many({'watch_uuid': watch_uuid})