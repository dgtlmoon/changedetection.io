import os
import io
import json
import brotli
import zlib
import time
from loguru import logger
import boto3
from urllib.parse import urlparse
import base64

from .storage_base import StorageBase

class S3Storage(StorageBase):
    """Amazon S3 storage backend"""
    
    def __init__(self, datastore_path, include_default_watches=True, version_tag="0.0.0"):
        """Initialize the S3 storage backend
        
        Args:
            datastore_path (str): S3 URI (s3://bucket-name/optional-prefix)
            include_default_watches (bool): Whether to include default watches
            version_tag (str): Version tag
        """
        # Parse S3 URI
        parsed_uri = urlparse(datastore_path)
        self.bucket_name = parsed_uri.netloc
        self.prefix = parsed_uri.path.lstrip('/')
        
        if self.prefix and not self.prefix.endswith('/'):
            self.prefix += '/'
            
        # Initialize S3 client
        # Uses AWS credentials from environment variables or IAM role
        self.s3 = boto3.client('s3')
        
        logger.info(f"S3 storage initialized, using bucket '{self.bucket_name}' with prefix '{self.prefix}'")
    
    def _get_key(self, path):
        """Get the S3 key for a path
        
        Args:
            path (str): Path relative to the prefix
            
        Returns:
            str: The full S3 key
        """
        return f"{self.prefix}{path}"
    
    def load_data(self):
        """Load data from S3
        
        Returns:
            dict: The loaded data
        """
        key = self._get_key("app-data.json")
        
        try:
            response = self.s3.get_object(Bucket=self.bucket_name, Key=key)
            return json.loads(response['Body'].read().decode('utf-8'))
        except self.s3.exceptions.NoSuchKey:
            return None
        except Exception as e:
            logger.error(f"Error loading data from S3: {str(e)}")
            raise e
    
    def save_data(self, data):
        """Save data to S3
        
        Args:
            data (dict): The data to save
        """
        try:
            key = self._get_key("app-data.json")
            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=json.dumps(data, indent=4),
                ContentType='application/json'
            )
        except Exception as e:
            logger.error(f"Error saving data to S3: {str(e)}")
            raise e
    
    def ensure_data_dir_exists(self, watch_uuid):
        """Ensure the data directory exists for a watch
        
        Args:
            watch_uuid (str): Watch UUID
        """
        # S3 doesn't need directories, this is a no-op
        pass
    
    def _get_watch_prefix(self, watch_uuid):
        """Get the S3 prefix for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            
        Returns:
            str: The watch prefix
        """
        return self._get_key(f"watches/{watch_uuid}/")
    
    def save_history_text(self, watch_uuid, contents, timestamp, snapshot_id):
        """Save history text to S3
        
        Args:
            watch_uuid (str): Watch UUID
            contents (str): Contents to save
            timestamp (int): Timestamp
            snapshot_id (str): Snapshot ID
            
        Returns:
            str: Snapshot ID
        """
        # Determine if we should compress
        threshold = int(os.getenv('SNAPSHOT_BROTLI_COMPRESSION_THRESHOLD', 1024))
        skip_brotli = os.getenv('DISABLE_BROTLI_TEXT_SNAPSHOT', 'False').lower() in ('true', '1', 't')
        
        watch_prefix = self._get_watch_prefix(watch_uuid)
        
        # Save the snapshot
        if not skip_brotli and len(contents) > threshold:
            snapshot_key = f"{watch_prefix}snapshots/{snapshot_id}.txt.br"
            snapshot_fname = f"{snapshot_id}.txt.br"
            compressed_contents = brotli.compress(contents.encode('utf-8'), mode=brotli.MODE_TEXT)
            
            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=snapshot_key,
                Body=compressed_contents
            )
        else:
            snapshot_key = f"{watch_prefix}snapshots/{snapshot_id}.txt"
            snapshot_fname = f"{snapshot_id}.txt"
            
            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=snapshot_key,
                Body=contents.encode('utf-8')
            )
        
        # Update history index
        history_key = f"{watch_prefix}history.txt"
        
        # Try to get existing history first
        try:
            response = self.s3.get_object(Bucket=self.bucket_name, Key=history_key)
            history_content = response['Body'].read().decode('utf-8')
        except self.s3.exceptions.NoSuchKey:
            history_content = ""
        
        # Append new entry
        history_content += f"{timestamp},{snapshot_fname}\n"
        
        # Save updated history
        self.s3.put_object(
            Bucket=self.bucket_name,
            Key=history_key,
            Body=history_content
        )
        
        return snapshot_fname
    
    def get_history(self, watch_uuid):
        """Get history for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            
        Returns:
            dict: The history with timestamp keys and snapshot IDs as values
        """
        tmp_history = {}
        watch_prefix = self._get_watch_prefix(watch_uuid)
        history_key = f"{watch_prefix}history.txt"
        
        try:
            response = self.s3.get_object(Bucket=self.bucket_name, Key=history_key)
            history_content = response['Body'].read().decode('utf-8')
            
            for line in history_content.splitlines():
                if ',' in line:
                    k, v = line.strip().split(',', 2)
                    tmp_history[k] = f"{watch_prefix}snapshots/{v}"
            
            return tmp_history
        except self.s3.exceptions.NoSuchKey:
            return {}
    
    def get_history_snapshot(self, watch_uuid, timestamp):
        """Get a history snapshot from S3
        
        Args:
            watch_uuid (str): Watch UUID
            timestamp (int): Timestamp
            
        Returns:
            str: The snapshot content
        """
        history = self.get_history(watch_uuid)
        if not timestamp in history:
            return None
            
        key = history[timestamp]
        
        try:
            response = self.s3.get_object(Bucket=self.bucket_name, Key=key)
            content = response['Body'].read()
            
            if key.endswith('.br'):
                # Decompress brotli
                return brotli.decompress(content).decode('utf-8')
            else:
                return content.decode('utf-8')
        except Exception as e:
            logger.error(f"Error reading snapshot from S3: {str(e)}")
            return None
    
    def save_screenshot(self, watch_uuid, screenshot, as_error=False):
        """Save a screenshot for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            screenshot (bytes): Screenshot data
            as_error (bool): Whether this is an error screenshot
        """
        watch_prefix = self._get_watch_prefix(watch_uuid)
        
        if as_error:
            key = f"{watch_prefix}last-error-screenshot.png"
        else:
            key = f"{watch_prefix}last-screenshot.png"
        
        self.s3.put_object(
            Bucket=self.bucket_name,
            Key=key,
            Body=screenshot,
            ContentType='image/png'
        )
    
    def get_screenshot(self, watch_uuid, is_error=False):
        """Get a screenshot for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            is_error (bool): Whether to get the error screenshot
            
        Returns:
            bytes or None: The screenshot data or None if not available
        """
        watch_prefix = self._get_watch_prefix(watch_uuid)
        
        if is_error:
            key = f"{watch_prefix}last-error-screenshot.png"
        else:
            key = f"{watch_prefix}last-screenshot.png"
        
        try:
            response = self.s3.get_object(Bucket=self.bucket_name, Key=key)
            return response['Body'].read()
        except self.s3.exceptions.NoSuchKey:
            return None
    
    def save_error_text(self, watch_uuid, contents):
        """Save error text for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            contents (str): Error contents
        """
        watch_prefix = self._get_watch_prefix(watch_uuid)
        key = f"{watch_prefix}last-error.txt"
        
        self.s3.put_object(
            Bucket=self.bucket_name,
            Key=key,
            Body=contents.encode('utf-8')
        )
    
    def get_error_text(self, watch_uuid):
        """Get error text for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            
        Returns:
            str or False: The error text or False if not available
        """
        watch_prefix = self._get_watch_prefix(watch_uuid)
        key = f"{watch_prefix}last-error.txt"
        
        try:
            response = self.s3.get_object(Bucket=self.bucket_name, Key=key)
            return response['Body'].read().decode('utf-8')
        except self.s3.exceptions.NoSuchKey:
            return False
    
    def save_xpath_data(self, watch_uuid, data, as_error=False):
        """Save XPath data for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            data (dict): XPath data
            as_error (bool): Whether this is error data
        """
        watch_prefix = self._get_watch_prefix(watch_uuid)
        
        if as_error:
            key = f"{watch_prefix}elements-error.deflate"
        else:
            key = f"{watch_prefix}elements.deflate"
        
        compressed_data = zlib.compress(json.dumps(data).encode())
        
        self.s3.put_object(
            Bucket=self.bucket_name,
            Key=key,
            Body=compressed_data
        )
    
    def get_xpath_data(self, watch_uuid, is_error=False):
        """Get XPath data for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            is_error (bool): Whether to get error data
            
        Returns:
            dict or None: The XPath data or None if not available
        """
        watch_prefix = self._get_watch_prefix(watch_uuid)
        
        if is_error:
            key = f"{watch_prefix}elements-error.deflate"
        else:
            key = f"{watch_prefix}elements.deflate"
        
        try:
            response = self.s3.get_object(Bucket=self.bucket_name, Key=key)
            compressed_data = response['Body'].read()
            return json.loads(zlib.decompress(compressed_data).decode('utf-8'))
        except self.s3.exceptions.NoSuchKey:
            return None
    
    def save_last_fetched_html(self, watch_uuid, timestamp, contents):
        """Save last fetched HTML for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            timestamp (int): Timestamp
            contents (str): HTML contents
        """
        watch_prefix = self._get_watch_prefix(watch_uuid)
        key = f"{watch_prefix}html/{timestamp}.html.br"
        
        contents_bytes = contents.encode('utf-8') if isinstance(contents, str) else contents
        try:
            compressed_contents = brotli.compress(contents_bytes)
        except Exception as e:
            logger.warning(f"{watch_uuid} - Unable to compress HTML snapshot: {str(e)}")
            compressed_contents = contents_bytes
        
        self.s3.put_object(
            Bucket=self.bucket_name,
            Key=key,
            Body=compressed_contents
        )
        
        # Prune old snapshots - keep only the newest 2
        self._prune_last_fetched_html_snapshots(watch_uuid)
    
    def _prune_last_fetched_html_snapshots(self, watch_uuid):
        """Prune old HTML snapshots
        
        Args:
            watch_uuid (str): Watch UUID
        """
        watch_prefix = self._get_watch_prefix(watch_uuid)
        html_prefix = f"{watch_prefix}html/"
        
        # List all HTML snapshots
        response = self.s3.list_objects_v2(
            Bucket=self.bucket_name,
            Prefix=html_prefix
        )
        
        if 'Contents' not in response:
            return
            
        # Sort by timestamp (extract from key)
        html_files = sorted(
            response['Contents'],
            key=lambda x: int(x['Key'].split('/')[-1].split('.')[0]),
            reverse=True
        )
        
        # Delete all but the newest 2
        if len(html_files) > 2:
            for file in html_files[2:]:
                self.s3.delete_object(
                    Bucket=self.bucket_name,
                    Key=file['Key']
                )
    
    def get_fetched_html(self, watch_uuid, timestamp):
        """Get fetched HTML for a watch
        
        Args:
            watch_uuid (str): Watch UUID
            timestamp (int): Timestamp
            
        Returns:
            str or False: The HTML or False if not available
        """
        watch_prefix = self._get_watch_prefix(watch_uuid)
        key = f"{watch_prefix}html/{timestamp}.html.br"
        
        try:
            response = self.s3.get_object(Bucket=self.bucket_name, Key=key)
            compressed_data = response['Body'].read()
            return brotli.decompress(compressed_data).decode('utf-8')
        except self.s3.exceptions.NoSuchKey:
            return False
    
    def save_last_text_fetched_before_filters(self, watch_uuid, contents):
        """Save the last text fetched before filters
        
        Args:
            watch_uuid (str): Watch UUID
            contents (str): Text contents
        """
        watch_prefix = self._get_watch_prefix(watch_uuid)
        key = f"{watch_prefix}last-fetched.br"
        
        compressed_contents = brotli.compress(contents.encode('utf-8'), mode=brotli.MODE_TEXT)
        
        self.s3.put_object(
            Bucket=self.bucket_name,
            Key=key,
            Body=compressed_contents
        )
    
    def get_last_fetched_text_before_filters(self, watch_uuid):
        """Get the last text fetched before filters
        
        Args:
            watch_uuid (str): Watch UUID
            
        Returns:
            str: The text
        """
        watch_prefix = self._get_watch_prefix(watch_uuid)
        key = f"{watch_prefix}last-fetched.br"
        
        try:
            response = self.s3.get_object(Bucket=self.bucket_name, Key=key)
            compressed_data = response['Body'].read()
            return brotli.decompress(compressed_data).decode('utf-8')
        except self.s3.exceptions.NoSuchKey:
            # If a previous attempt doesnt yet exist, just snarf the previous snapshot instead
            history = self.get_history(watch_uuid)
            dates = list(history.keys())
            
            if len(dates):
                return self.get_history_snapshot(watch_uuid, dates[-1])
            else:
                return ''
    
    def visualselector_data_is_ready(self, watch_uuid):
        """Check if visual selector data is ready
        
        Args:
            watch_uuid (str): Watch UUID
            
        Returns:
            bool: Whether visual selector data is ready
        """
        watch_prefix = self._get_watch_prefix(watch_uuid)
        screenshot_key = f"{watch_prefix}last-screenshot.png"
        elements_key = f"{watch_prefix}elements.deflate"
        
        try:
            # Just check if both files exist
            self.s3.head_object(Bucket=self.bucket_name, Key=screenshot_key)
            self.s3.head_object(Bucket=self.bucket_name, Key=elements_key)
            return True
        except self.s3.exceptions.ClientError:
            return False
    
    def clear_watch_history(self, watch_uuid):
        """Clear history for a watch
        
        Args:
            watch_uuid (str): Watch UUID
        """
        watch_prefix = self._get_watch_prefix(watch_uuid)
        
        # List all objects with this watch's prefix
        paginator = self.s3.get_paginator('list_objects_v2')
        pages = paginator.paginate(
            Bucket=self.bucket_name,
            Prefix=watch_prefix
        )
        
        # Delete all objects in batches
        for page in pages:
            if 'Contents' not in page:
                continue
                
            delete_keys = {'Objects': [{'Key': obj['Key']} for obj in page['Contents']]}
            self.s3.delete_objects(
                Bucket=self.bucket_name,
                Delete=delete_keys
            )
    
    def delete_watch(self, watch_uuid):
        """Delete a watch
        
        Args:
            watch_uuid (str): Watch UUID
        """
        # Same implementation as clear_watch_history for S3
        self.clear_watch_history(watch_uuid)