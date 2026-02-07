"""
File-based datastore with individual watch persistence and immediate commits.

This module provides the FileSavingDataStore abstract class that implements:
- Individual watch.json file persistence
- Immediate commit-based persistence (watch.commit(), datastore.commit())
- Atomic file writes safe for NFS/NAS
"""

import glob
import json
import os
import tempfile
import time
from loguru import logger

from .base import DataStore
from .. import strtobool

# Try to import orjson for faster JSON serialization
try:
    import orjson
    HAS_ORJSON = True
except ImportError:
    HAS_ORJSON = False

# Fsync configuration: Force file data to disk for crash safety
# Default False to match legacy behavior (write-and-rename without fsync)
# Set to True for mission-critical deployments requiring crash consistency
FORCE_FSYNC_DATA_IS_CRITICAL = bool(strtobool(os.getenv('FORCE_FSYNC_DATA_IS_CRITICAL', 'False')))

# ============================================================================
# Helper Functions for Atomic File Operations
# ============================================================================

def save_json_atomic(file_path, data_dict, label="file", max_size_mb=10):
    """
    Save JSON data to disk using atomic write pattern.

    Generic helper for saving any JSON data (settings, watches, etc.) with:
    - Atomic write (temp file + rename)
    - Directory fsync for crash consistency (only for new files)
    - Size validation
    - Proper error handling

    Thread safety: Caller must hold datastore.lock to prevent concurrent modifications.
    Multi-process safety: Not supported - run only one app instance per datastore.

    Args:
        file_path: Full path to target JSON file
        data_dict: Dictionary to serialize
        label: Human-readable label for error messages (e.g., "watch", "settings")
        max_size_mb: Maximum allowed file size in MB

    Raises:
        ValueError: If serialized data exceeds max_size_mb
        OSError: If disk is full (ENOSPC) or other I/O error
    """
    # Check if file already exists (before we start writing)
    # Directory fsync only needed for NEW files to persist the filename
    file_exists = os.path.exists(file_path)

    # Ensure parent directory exists
    parent_dir = os.path.dirname(file_path)
    os.makedirs(parent_dir, exist_ok=True)

    # Create temp file in same directory (required for NFS atomicity)
    fd, temp_path = tempfile.mkstemp(
        suffix='.tmp',
        prefix='json-',
        dir=parent_dir,
        text=False
    )

    fd_closed = False
    try:
        # Serialize data
        t0 = time.time()
        if HAS_ORJSON:
            data = orjson.dumps(data_dict, option=orjson.OPT_INDENT_2)
        else:
            data = json.dumps(data_dict, indent=2, ensure_ascii=False).encode('utf-8')
        serialize_ms = (time.time() - t0) * 1000

        # Safety check: validate size
        MAX_SIZE = max_size_mb * 1024 * 1024
        data_size = len(data)
        if data_size > MAX_SIZE:
            raise ValueError(
                f"{label.capitalize()} data is unexpectedly large: {data_size / 1024 / 1024:.2f}MB "
                f"(max: {max_size_mb}MB). This indicates a bug or data corruption."
            )

        # Write to temp file
        t1 = time.time()
        os.write(fd, data)
        write_ms = (time.time() - t1) * 1000

        # Optional fsync: Force file data to disk for crash safety
        # Only if FORCE_FSYNC_DATA_IS_CRITICAL=True (default: False, matches legacy behavior)
        t2 = time.time()
        if FORCE_FSYNC_DATA_IS_CRITICAL:
            os.fsync(fd)
        file_fsync_ms = (time.time() - t2) * 1000

        os.close(fd)
        fd_closed = True

        # Atomic rename
        t3 = time.time()
        os.replace(temp_path, file_path)
        rename_ms = (time.time() - t3) * 1000

        # Sync directory to ensure filename metadata is durable
        # OPTIMIZATION: Only needed for NEW files. Existing files already have
        # directory entry persisted, so we only need file fsync for data durability.
        dir_fsync_ms = 0
        if not file_exists:
            try:
                dir_fd = os.open(parent_dir, os.O_RDONLY)
                try:
                    t4 = time.time()
                    os.fsync(dir_fd)
                    dir_fsync_ms = (time.time() - t4) * 1000
                finally:
                    os.close(dir_fd)
            except (OSError, AttributeError):
                # Windows doesn't support fsync on directories
                pass

        # Log timing breakdown for slow saves
#        total_ms = serialize_ms + write_ms + file_fsync_ms + rename_ms + dir_fsync_ms
#        if total_ms:  # Log if save took more than 10ms
#            file_status = "new" if not file_exists else "update"
#            logger.trace(
#                f"Save timing breakdown ({total_ms:.1f}ms total, {file_status}): "
#                f"serialize={serialize_ms:.1f}ms, write={write_ms:.1f}ms, "
#                f"file_fsync={file_fsync_ms:.1f}ms, rename={rename_ms:.1f}ms, "
#                f"dir_fsync={dir_fsync_ms:.1f}ms, using_orjson={HAS_ORJSON}"
#            )

    except OSError as e:
        # Cleanup temp file
        if not fd_closed:
            try:
                os.close(fd)
            except:
                pass
        if os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except:
                pass

        # Provide helpful error messages
        if e.errno == 28:  # ENOSPC
            raise OSError(f"Disk full: Cannot save {label}") from e
        elif e.errno == 122:  # EDQUOT
            raise OSError(f"Disk quota exceeded: Cannot save {label}") from e
        else:
            raise OSError(f"I/O error saving {label}: {e}") from e

    except Exception as e:
        # Cleanup temp file
        if not fd_closed:
            try:
                os.close(fd)
            except:
                pass
        if os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except:
                pass
        raise e


def save_entity_atomic(entity_dir, uuid, entity_dict, filename, entity_type, max_size_mb):
    """
    Save an entity (watch/tag) to disk using atomic write pattern.

    Generic function for saving any watch_base subclass (Watch, Tag, etc.).

    Args:
        entity_dir: Directory for this entity (e.g., /datastore/{uuid})
        uuid: Entity UUID (for logging)
        entity_dict: Dictionary representation of the entity
        filename: JSON filename (e.g., 'watch.json', 'tag.json')
        entity_type: Type label for logging (e.g., 'watch', 'tag')
        max_size_mb: Maximum allowed file size in MB

    Raises:
        ValueError: If serialized data exceeds max_size_mb
        OSError: If disk is full (ENOSPC) or other I/O error
    """
    entity_json = os.path.join(entity_dir, filename)
    save_json_atomic(entity_json, entity_dict, label=f"{entity_type} {uuid}", max_size_mb=max_size_mb)


def save_watch_atomic(watch_dir, uuid, watch_dict):
    """
    Save a watch to disk using atomic write pattern.

    Convenience wrapper around save_entity_atomic for watches.
    Kept for backwards compatibility.
    """
    save_entity_atomic(watch_dir, uuid, watch_dict, "watch.json", "watch", max_size_mb=10)


def save_tag_atomic(tag_dir, uuid, tag_dict):
    """
    Save a tag to disk using atomic write pattern.

    Convenience wrapper around save_entity_atomic for tags.
    Kept for backwards compatibility.
    """
    save_entity_atomic(tag_dir, uuid, tag_dict, "tag.json", "tag", max_size_mb=1)


def load_watch_from_file(watch_json, uuid, rehydrate_entity_func):
    """
    Load a watch from its JSON file.

    Args:
        watch_json: Path to the watch.json file
        uuid: Watch UUID
        rehydrate_entity_func: Function to convert dict to Watch object

    Returns:
        Watch object or None if failed
    """
    try:
        # Check file size before reading
        file_size = os.path.getsize(watch_json)
        MAX_WATCH_SIZE = 10 * 1024 * 1024  # 10MB
        if file_size > MAX_WATCH_SIZE:
            logger.critical(
                f"CORRUPTED WATCH DATA: Watch {uuid} file is unexpectedly large: "
                f"{file_size / 1024 / 1024:.2f}MB (max: {MAX_WATCH_SIZE / 1024 / 1024}MB). "
                f"File: {watch_json}. This indicates a bug or data corruption. "
                f"Watch will be skipped."
            )
            return None

        if HAS_ORJSON:
            with open(watch_json, 'rb') as f:
                watch_data = orjson.loads(f.read())
        else:
            with open(watch_json, 'r', encoding='utf-8') as f:
                watch_data = json.load(f)

        # Rehydrate and return watch object
        watch_obj = rehydrate_entity_func(uuid, watch_data)
        return watch_obj

    except json.JSONDecodeError as e:
        logger.critical(
            f"CORRUPTED WATCH DATA: Failed to parse JSON for watch {uuid}. "
            f"File: {watch_json}. Error: {e}. "
            f"Watch will be skipped and may need manual recovery from backup."
        )
        return None
    except ValueError as e:
        # orjson raises ValueError for invalid JSON
        if "invalid json" in str(e).lower() or HAS_ORJSON:
            logger.critical(
                f"CORRUPTED WATCH DATA: Failed to parse JSON for watch {uuid}. "
                f"File: {watch_json}. Error: {e}. "
                f"Watch will be skipped and may need manual recovery from backup."
            )
            return None
        # Re-raise if it's not a JSON parsing error
        raise
    except FileNotFoundError:
        logger.error(f"Watch file not found: {watch_json} for watch {uuid}")
        return None
    except Exception as e:
        logger.error(f"Failed to load watch {uuid} from {watch_json}: {e}")
        return None


def load_all_watches(datastore_path, rehydrate_entity_func):
    """
    Load all watches from individual watch.json files.

    SYNCHRONOUS loading: Blocks until all watches are loaded.
    This ensures data consistency - web server won't accept requests
    until all watches are available. Progress logged every 100 watches.

    Args:
        datastore_path: Path to the datastore directory
        rehydrate_entity_func: Function to convert dict to Watch object

    Returns:
        Dictionary of uuid -> Watch object
    """
    start_time = time.time()
    logger.info("Loading watches from individual watch.json files...")

    watching = {}

    if not os.path.exists(datastore_path):
        return watching

    # Find all watch.json files using glob (faster than manual directory traversal)
    glob_start = time.time()
    watch_files = glob.glob(os.path.join(datastore_path, "*", "watch.json"))
    glob_time = time.time() - glob_start

    total = len(watch_files)
    logger.debug(f"Found {total} watch.json files in {glob_time:.3f}s")

    loaded = 0
    failed = 0

    for watch_json in watch_files:
        # Extract UUID from path: /datastore/{uuid}/watch.json
        uuid_dir = os.path.basename(os.path.dirname(watch_json))
        watch = load_watch_from_file(watch_json, uuid_dir, rehydrate_entity_func)
        if watch:
            watching[uuid_dir] = watch
            loaded += 1

            if loaded % 100 == 0:
                logger.info(f"Loaded {loaded}/{total} watches...")
        else:
            # load_watch_from_file already logged the specific error
            failed += 1

    elapsed = time.time() - start_time

    if failed > 0:
        logger.critical(
            f"LOAD COMPLETE: {loaded} watches loaded successfully, "
            f"{failed} watches FAILED to load (corrupted or invalid) "
            f"in {elapsed:.2f}s ({loaded/elapsed:.0f} watches/sec)"
        )
    else:
        logger.info(f"Loaded {loaded} watches from disk in {elapsed:.2f}s ({loaded/elapsed:.0f} watches/sec)")

    return watching


def load_tag_from_file(tag_json, uuid, rehydrate_entity_func):
    """
    Load a tag from its JSON file.

    Args:
        tag_json: Path to the tag.json file
        uuid: Tag UUID
        rehydrate_entity_func: Function to convert dict to Tag object

    Returns:
        Tag object or None if failed
    """
    try:
        # Check file size before reading
        file_size = os.path.getsize(tag_json)
        MAX_TAG_SIZE = 1 * 1024 * 1024  # 1MB
        if file_size > MAX_TAG_SIZE:
            logger.critical(
                f"CORRUPTED TAG DATA: Tag {uuid} file is unexpectedly large: "
                f"{file_size / 1024 / 1024:.2f}MB (max: {MAX_TAG_SIZE / 1024 / 1024}MB). "
                f"File: {tag_json}. This indicates a bug or data corruption. "
                f"Tag will be skipped."
            )
            return None

        if HAS_ORJSON:
            with open(tag_json, 'rb') as f:
                tag_data = orjson.loads(f.read())
        else:
            with open(tag_json, 'r', encoding='utf-8') as f:
                tag_data = json.load(f)

        # Rehydrate tag (convert dict to Tag object)
        tag_obj = rehydrate_entity_func(uuid, tag_data, processor_override='restock_diff')
        return tag_obj

    except json.JSONDecodeError as e:
        logger.critical(
            f"CORRUPTED TAG DATA: Failed to parse JSON for tag {uuid}. "
            f"File: {tag_json}. Error: {e}. "
            f"Tag will be skipped and may need manual recovery from backup."
        )
        return None
    except ValueError as e:
        # orjson raises ValueError for invalid JSON
        if "invalid json" in str(e).lower() or HAS_ORJSON:
            logger.critical(
                f"CORRUPTED TAG DATA: Failed to parse JSON for tag {uuid}. "
                f"File: {tag_json}. Error: {e}. "
                f"Tag will be skipped and may need manual recovery from backup."
            )
            return None
        # Re-raise if it's not a JSON parsing error
        raise
    except FileNotFoundError:
        logger.debug(f"Tag file not found: {tag_json} for tag {uuid}")
        return None
    except Exception as e:
        logger.error(f"Failed to load tag {uuid} from {tag_json}: {e}")
        return None


def load_all_tags(datastore_path, rehydrate_entity_func):
    """
    Load all tags from individual tag.json files.

    Tags are stored separately from settings in {uuid}/tag.json files.

    Args:
        datastore_path: Path to the datastore directory
        rehydrate_entity_func: Function to convert dict to Tag object

    Returns:
        Dictionary of uuid -> Tag object
    """
    logger.info("Loading tags from individual tag.json files...")

    tags = {}

    if not os.path.exists(datastore_path):
        return tags

    # Find all tag.json files using glob
    tag_files = glob.glob(os.path.join(datastore_path, "*", "tag.json"))

    total = len(tag_files)
    if total == 0:
        logger.debug("No tag.json files found")
        return tags

    logger.debug(f"Found {total} tag.json files")

    loaded = 0
    failed = 0

    for tag_json in tag_files:
        # Extract UUID from path: /datastore/{uuid}/tag.json
        uuid_dir = os.path.basename(os.path.dirname(tag_json))
        tag = load_tag_from_file(tag_json, uuid_dir, rehydrate_entity_func)
        if tag:
            tags[uuid_dir] = tag
            loaded += 1
        else:
            # load_tag_from_file already logged the specific error
            failed += 1

    if failed > 0:
        logger.warning(f"Loaded {loaded} tags, {failed} tags FAILED to load")
    else:
        logger.info(f"Loaded {loaded} tags from disk")

    return tags


# ============================================================================
# FileSavingDataStore Class
# ============================================================================

class FileSavingDataStore(DataStore):
    """
    Abstract datastore that provides file persistence with immediate commits.

    Features:
    - Individual watch.json files (one per watch)
    - Immediate persistence via watch.commit() and datastore.commit()
    - Atomic file writes for crash safety

    Subclasses must implement:
    - rehydrate_entity(): Convert dict to Watch object
    - Access to internal __data structure for watch management
    """

    def __init__(self):
        super().__init__()

    def _save_settings(self):
        """
        Save settings to storage (polymorphic).

        Subclasses must implement for their backend.
        - File: changedetection.json
        - Redis: SET settings
        - SQL: UPDATE settings table
        """
        raise NotImplementedError("Subclass must implement _save_settings")


    def _load_watches(self):
        """
        Load all watches from storage (polymorphic).

        Subclasses must implement for their backend.
        - File: Read individual watch.json files
        - Redis: SCAN watch:* keys
        - SQL: SELECT * FROM watches
        """
        raise NotImplementedError("Subclass must implement _load_watches")

    def _delete_watch(self, uuid):
        """
        Delete a watch from storage (polymorphic).

        Subclasses must implement for their backend.
        - File: Delete {uuid}/ directory recursively
        - Redis: DEL watch:{uuid}
        - SQL: DELETE FROM watches WHERE uuid=?

        Args:
            uuid: Watch UUID to delete
        """
        raise NotImplementedError("Subclass must implement _delete_watch")


