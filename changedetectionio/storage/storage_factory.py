import re
from loguru import logger
from urllib.parse import urlparse

from .storage_base import StorageBase
from .filesystem_storage import FileSystemStorage
from .mongodb_storage import MongoDBStorage
from .s3_storage import S3Storage

def create_storage(datastore_path, include_default_watches=True, version_tag="0.0.0"):
    """Create a storage backend based on the datastore path
    
    Args:
        datastore_path (str): Path to the datastore
        include_default_watches (bool): Whether to include default watches
        version_tag (str): Version tag
        
    Returns:
        StorageBase: The storage backend
    """
    # Check if it's a MongoDB URI
    if datastore_path.startswith('mongodb://') or datastore_path.startswith('mongodb+srv://'):
        logger.info(f"Using MongoDB storage backend with URI {datastore_path}")
        return MongoDBStorage(datastore_path, include_default_watches, version_tag)
    
    # Check if it's an S3 URI
    if datastore_path.startswith('s3://'):
        logger.info(f"Using S3 storage backend with URI {datastore_path}")
        return S3Storage(datastore_path, include_default_watches, version_tag)
    
    # Default to filesystem
    logger.info(f"Using filesystem storage backend with path {datastore_path}")
    return FileSystemStorage(datastore_path, include_default_watches, version_tag)