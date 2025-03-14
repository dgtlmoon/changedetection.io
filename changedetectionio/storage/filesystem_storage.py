import os
import shutil
import json
import brotli
import zlib
import pathlib
from loguru import logger
from os import path

from .storage_base import StorageBase

class FileSystemStorage(StorageBase):
    """File system storage backend"""
    
    def __init__(self, datastore_path, include_default_watches=True, version_tag="0.0.0"):
        """Initialize the file system storage backend
        
        Args:
            datastore_path (str): Path to the datastore
            include_default_watches (bool): Whether to include default watches
            version_tag (str): Version tag
        """
        self.datastore_path = datastore_path
        self.json_store_path = "{}/url-watches.json".format(self.datastore_path)
        logger.info(f"Datastore path is '{self.json_store_path}'")
        
    def load_data(self):
        """Load data from the file system
        
        Returns:
            dict: The loaded data
        """
        if not path.isfile(self.json_store_path):
            return None
            
        with open(self.json_store_path) as json_file:
            return json.load(json_file)

    def save_data(self, data):
        """Save data to the file system
        
        Args:
            data (dict): The data to save
        """
        try:
            # Re #286 - First write to a temp file, then confirm it looks OK and rename it
            # This is a fairly basic strategy to deal with the case that the file is corrupted,
            # system was out of memory, out of RAM etc
            with open(self.json_store_path+".tmp", 'w') as json_file:
                json.dump(data, json_file, indent=4)
            os.replace(self.json_store_path+".tmp", self.json_store_path)
        except Exception as e:
            logger.error(f"Error writing JSON!! (Main JSON file save was skipped) : {str(e)}")
            raise e
    
    def get_watch_dir(self, watch_uuid):
        """Get the directory for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            
        Returns:
            str: The watch directory
        """
        return os.path.join(self.datastore_path, watch_uuid)
    
    def ensure_data_dir_exists(self, watch_uuid):
        """Ensure the data directory exists for a watch
        
        Args:
            watch_uuid (str): Watch UUID
        """
        watch_dir = self.get_watch_dir(watch_uuid)
        if not os.path.isdir(watch_dir):
            logger.debug(f"> Creating data dir {watch_dir}")
            os.makedirs(watch_dir, exist_ok=True)
    
    def save_history_text(self, watch_uuid, contents, timestamp, snapshot_id):
        """Save history text to the file system
        
        Args:
            watch_uuid (str): Watch UUID
            contents (str): Contents to save
            timestamp (int): Timestamp
            snapshot_id (str): Snapshot ID
            
        Returns:
            str: Snapshot filename
        """
        self.ensure_data_dir_exists(watch_uuid)
        
        threshold = int(os.getenv('SNAPSHOT_BROTLI_COMPRESSION_THRESHOLD', 1024))
        skip_brotli = os.getenv('DISABLE_BROTLI_TEXT_SNAPSHOT', 'False').lower() in ('true', '1', 't')
        
        watch_dir = self.get_watch_dir(watch_uuid)
        
        if not skip_brotli and len(contents) > threshold:
            snapshot_fname = f"{snapshot_id}.txt.br"
            dest = os.path.join(watch_dir, snapshot_fname)
            if not os.path.exists(dest):
                with open(dest, 'wb') as f:
                    f.write(brotli.compress(contents.encode('utf-8'), mode=brotli.MODE_TEXT))
        else:
            snapshot_fname = f"{snapshot_id}.txt"
            dest = os.path.join(watch_dir, snapshot_fname)
            if not os.path.exists(dest):
                with open(dest, 'wb') as f:
                    f.write(contents.encode('utf-8'))
        
        # Append to index
        index_fname = os.path.join(watch_dir, "history.txt")
        with open(index_fname, 'a') as f:
            f.write("{},{}\n".format(timestamp, snapshot_fname))
        
        return snapshot_fname
    
    def get_history(self, watch_uuid):
        """Get history for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            
        Returns:
            dict: The history with timestamp keys and snapshot IDs as values
        """
        tmp_history = {}
        
        watch_dir = self.get_watch_dir(watch_uuid)
        if not os.path.isdir(watch_dir):
            return tmp_history
        
        # Read the history file as a dict
        fname = os.path.join(watch_dir, "history.txt")
        if os.path.isfile(fname):
            logger.debug(f"Reading watch history index for {watch_uuid}")
            with open(fname, "r") as f:
                for i in f.readlines():
                    if ',' in i:
                        k, v = i.strip().split(',', 2)
                        
                        # The index history could contain a relative path, so we need to make the fullpath
                        # so that python can read it
                        if not '/' in v and not '\'' in v:
                            v = os.path.join(watch_dir, v)
                        else:
                            # It's possible that they moved the datadir on older versions
                            # So the snapshot exists but is in a different path
                            snapshot_fname = v.split('/')[-1]
                            proposed_new_path = os.path.join(watch_dir, snapshot_fname)
                            if not os.path.exists(v) and os.path.exists(proposed_new_path):
                                v = proposed_new_path
                        
                        tmp_history[k] = v
        
        return tmp_history
    
    def get_history_snapshot(self, watch_uuid, timestamp):
        """Get a history snapshot from the file system
        
        Args:
            watch_uuid (str): Watch UUID
            timestamp (int): Timestamp
            
        Returns:
            str: The snapshot content
        """
        history = self.get_history(watch_uuid)
        if not timestamp in history:
            return None
            
        filepath = history[timestamp]
        
        # See if a brotli versions exists and switch to that
        if not filepath.endswith('.br') and os.path.isfile(f"{filepath}.br"):
            filepath = f"{filepath}.br"
        
        # OR in the backup case that the .br does not exist, but the plain one does
        if filepath.endswith('.br') and not os.path.isfile(filepath):
            if os.path.isfile(filepath.replace('.br', '')):
                filepath = filepath.replace('.br', '')
        
        if filepath.endswith('.br'):
            # Brotli doesnt have a fileheader to detect it, so we rely on filename
            # https://www.rfc-editor.org/rfc/rfc7932
            with open(filepath, 'rb') as f:
                return(brotli.decompress(f.read()).decode('utf-8'))
        
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    
    def save_screenshot(self, watch_uuid, screenshot, as_error=False):
        """Save a screenshot for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            screenshot (bytes): Screenshot data
            as_error (bool): Whether this is an error screenshot
        """
        self.ensure_data_dir_exists(watch_uuid)
        watch_dir = self.get_watch_dir(watch_uuid)
        
        if as_error:
            target_path = os.path.join(watch_dir, "last-error-screenshot.png")
        else:
            target_path = os.path.join(watch_dir, "last-screenshot.png")
        
        with open(target_path, 'wb') as f:
            f.write(screenshot)
    
    def get_screenshot(self, watch_uuid, is_error=False):
        """Get a screenshot for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            is_error (bool): Whether to get the error screenshot
            
        Returns:
            str or None: The screenshot path or None if not available
        """
        watch_dir = self.get_watch_dir(watch_uuid)
        
        if is_error:
            fname = os.path.join(watch_dir, "last-error-screenshot.png")
        else:
            fname = os.path.join(watch_dir, "last-screenshot.png")
            
        if os.path.isfile(fname):
            return fname
        
        return None
    
    def save_error_text(self, watch_uuid, contents):
        """Save error text for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            contents (str): Error contents
        """
        self.ensure_data_dir_exists(watch_uuid)
        watch_dir = self.get_watch_dir(watch_uuid)
        
        target_path = os.path.join(watch_dir, "last-error.txt")
        with open(target_path, 'w', encoding='utf-8') as f:
            f.write(contents)
    
    def get_error_text(self, watch_uuid):
        """Get error text for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            
        Returns:
            str or False: The error text or False if not available
        """
        watch_dir = self.get_watch_dir(watch_uuid)
        fname = os.path.join(watch_dir, "last-error.txt")
        
        if os.path.isfile(fname):
            with open(fname, 'r') as f:
                return f.read()
                
        return False
    
    def save_xpath_data(self, watch_uuid, data, as_error=False):
        """Save XPath data for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            data (dict): XPath data
            as_error (bool): Whether this is error data
        """
        self.ensure_data_dir_exists(watch_uuid)
        watch_dir = self.get_watch_dir(watch_uuid)
        
        if as_error:
            target_path = os.path.join(watch_dir, "elements-error.deflate")
        else:
            target_path = os.path.join(watch_dir, "elements.deflate")
        
        with open(target_path, 'wb') as f:
            f.write(zlib.compress(json.dumps(data).encode()))
    
    def get_xpath_data(self, watch_uuid, is_error=False):
        """Get XPath data for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            is_error (bool): Whether to get error data
            
        Returns:
            dict or None: The XPath data or None if not available
        """
        watch_dir = self.get_watch_dir(watch_uuid)
        
        if is_error:
            path = os.path.join(watch_dir, "elements-error.deflate")
        else:
            path = os.path.join(watch_dir, "elements.deflate")
            
        if not os.path.isfile(path):
            return None
            
        with open(path, 'rb') as f:
            return json.loads(zlib.decompress(f.read()).decode('utf-8'))
    
    def save_last_fetched_html(self, watch_uuid, timestamp, contents):
        """Save last fetched HTML for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            timestamp (int): Timestamp
            contents (str): HTML contents
        """
        self.ensure_data_dir_exists(watch_uuid)
        watch_dir = self.get_watch_dir(watch_uuid)
        
        snapshot_fname = f"{timestamp}.html.br"
        filepath = os.path.join(watch_dir, snapshot_fname)
        
        with open(filepath, 'wb') as f:
            contents = contents.encode('utf-8') if isinstance(contents, str) else contents
            try:
                f.write(brotli.compress(contents))
            except Exception as e:
                logger.warning(f"{watch_uuid} - Unable to compress snapshot, saving as raw data to {filepath}")
                logger.warning(e)
                f.write(contents)
                
        # Prune old snapshots - keep only the newest 2
        self._prune_last_fetched_html_snapshots(watch_uuid)
    
    def _prune_last_fetched_html_snapshots(self, watch_uuid):
        """Prune old HTML snapshots
        
        Args:
            watch_uuid (str): Watch UUID
        """
        watch_dir = self.get_watch_dir(watch_uuid)
        history = self.get_history(watch_uuid)
        
        dates = list(history.keys())
        dates.reverse()
        
        for index, timestamp in enumerate(dates):
            snapshot_fname = f"{timestamp}.html.br"
            filepath = os.path.join(watch_dir, snapshot_fname)
            
            # Keep only the first 2
            if index > 1 and os.path.isfile(filepath):
                os.remove(filepath)
    
    def get_fetched_html(self, watch_uuid, timestamp):
        """Get fetched HTML for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            timestamp (int): Timestamp
            
        Returns:
            str or False: The HTML or False if not available
        """
        watch_dir = self.get_watch_dir(watch_uuid)
        
        snapshot_fname = f"{timestamp}.html.br"
        filepath = os.path.join(watch_dir, snapshot_fname)
        
        if os.path.isfile(filepath):
            with open(filepath, 'rb') as f:
                return brotli.decompress(f.read()).decode('utf-8')
                
        return False
    
    def save_last_text_fetched_before_filters(self, watch_uuid, contents):
        """Save the last text fetched before filters
        
        Args:
            watch_uuid (str): Watch UUID
            contents (str): Text contents
        """
        self.ensure_data_dir_exists(watch_uuid)
        watch_dir = self.get_watch_dir(watch_uuid)
        
        filepath = os.path.join(watch_dir, 'last-fetched.br')
        with open(filepath, 'wb') as f:
            f.write(brotli.compress(contents.encode('utf-8'), mode=brotli.MODE_TEXT))
    
    def get_last_fetched_text_before_filters(self, watch_uuid):
        """Get the last text fetched before filters
        
        Args:
            watch_uuid (str): Watch UUID
            
        Returns:
            str: The text
        """
        watch_dir = self.get_watch_dir(watch_uuid)
        filepath = os.path.join(watch_dir, 'last-fetched.br')
        
        if not os.path.isfile(filepath):
            # If a previous attempt doesnt yet exist, just snarf the previous snapshot instead
            history = self.get_history(watch_uuid)
            dates = list(history.keys())
            
            if len(dates):
                return self.get_history_snapshot(watch_uuid, dates[-1])
            else:
                return ''
        
        with open(filepath, 'rb') as f:
            return brotli.decompress(f.read()).decode('utf-8')
    
    def visualselector_data_is_ready(self, watch_uuid):
        """Check if visual selector data is ready
        
        Args:
            watch_uuid (str): Watch UUID
            
        Returns:
            bool: Whether visual selector data is ready
        """
        watch_dir = self.get_watch_dir(watch_uuid)
        screenshot_filename = os.path.join(watch_dir, "last-screenshot.png")
        elements_index_filename = os.path.join(watch_dir, "elements.deflate")
        
        return path.isfile(screenshot_filename) and path.isfile(elements_index_filename)
    
    def clear_watch_history(self, watch_uuid):
        """Clear history for a watch
        
        Args:
            watch_uuid (str): Watch UUID
        """
        watch_dir = self.get_watch_dir(watch_uuid)
        if not os.path.exists(watch_dir):
            return
            
        # Delete all files but keep the directory
        for item in pathlib.Path(watch_dir).glob("*.*"):
            os.unlink(item)
    
    def delete_watch(self, watch_uuid):
        """Delete a watch
        
        Args:
            watch_uuid (str): Watch UUID
        """
        watch_dir = self.get_watch_dir(watch_uuid)
        if os.path.exists(watch_dir):
            shutil.rmtree(watch_dir)