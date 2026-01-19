"""
Legacy format loader for url-watches.json.

Provides functions to detect and load from the legacy monolithic JSON format.
Used during migration (update_26) to transition to individual watch.json files.
"""

import os
import json
from loguru import logger

# Try to import orjson for faster JSON serialization
try:
    import orjson
    HAS_ORJSON = True
except ImportError:
    HAS_ORJSON = False


def detect_format(datastore_path):
    """
    Detect which datastore format is in use.

    Returns:
    - 'new': changedetection.json exists (new format)
    - 'empty': No changedetection.json (first run or needs migration)

    Note: Legacy url-watches.json detection is handled by update_26 during migration.
    Runtime only distinguishes between 'new' (already migrated) and 'empty' (needs setup/migration).

    Args:
        datastore_path: Path to datastore directory

    Returns:
        str: 'new' or 'empty'
    """
    changedetection_json = os.path.join(datastore_path, "changedetection.json")

    if os.path.exists(changedetection_json):
        return 'new'
    else:
        return 'empty'


def has_legacy_datastore(datastore_path):
    """
    Check if a legacy url-watches.json file exists.

    This is used by update_26 to determine if migration is needed.

    Args:
        datastore_path: Path to datastore directory

    Returns:
        bool: True if url-watches.json exists
    """
    url_watches_json = os.path.join(datastore_path, "url-watches.json")
    return os.path.exists(url_watches_json)


def load_legacy_format(json_store_path):
    """
    Load datastore from legacy url-watches.json format.

    Args:
        json_store_path: Full path to url-watches.json file

    Returns:
        dict: Loaded datastore data with 'watching', 'settings', etc.
        None: If file doesn't exist or loading failed
    """
    logger.info(f"Loading from legacy format: {json_store_path}")

    if not os.path.isfile(json_store_path):
        logger.warning(f"Legacy file not found: {json_store_path}")
        return None

    try:
        if HAS_ORJSON:
            with open(json_store_path, 'rb') as f:
                data = orjson.loads(f.read())
        else:
            with open(json_store_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

        logger.info(f"Loaded {len(data.get('watching', {}))} watches from legacy format")
        return data

    except Exception as e:
        logger.error(f"Failed to load legacy format: {e}")
        return None
