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
import sys
import tempfile
import time
from loguru import logger

# Cross-platform file locking
if sys.platform == 'win32':
    import msvcrt
    HAS_FCNTL = False
else:
    import fcntl
    HAS_FCNTL = True

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


def _lock_file(file_obj):
    """Acquire exclusive lock on file (cross-platform)."""
    if HAS_FCNTL:
        # Unix: use fcntl
        fcntl.flock(file_obj.fileno(), fcntl.LOCK_EX)
    else:
        # Windows: use msvcrt
        file_obj.seek(0)
        msvcrt.locking(file_obj.fileno(), msvcrt.LK_LOCK, 1)


def _unlock_file(file_obj):
    """Release lock on file (cross-platform)."""
    if HAS_FCNTL:
        # Unix: use fcntl
        fcntl.flock(file_obj.fileno(), fcntl.LOCK_UN)
    else:
        # Windows: use msvcrt
        file_obj.seek(0)
        msvcrt.locking(file_obj.fileno(), msvcrt.LK_UNLCK, 1)


# ============================================================================
# Helper Functions for Atomic File Operations
# ============================================================================

def save_json_atomic(file_path, data_dict, label="file", max_size_mb=10):
    """
    Save JSON data to disk using atomic write pattern with file locking.

    Generic helper for saving any JSON data (settings, watches, etc.) with:
    - File-level locking (protects against concurrent processes)
    - Atomic write (temp file + rename)
    - Directory fsync for crash consistency (only for new files)
    - Size validation
    - Proper error handling

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

    # Acquire file lock to prevent concurrent writes from multiple processes
    lock_path = file_path + '.lock'
    lock_file = open(lock_path, 'w')
    try:
        # Exclusive lock - blocks until acquired (cross-platform)
        _lock_file(lock_file)

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
#            total_ms = serialize_ms + write_ms + file_fsync_ms + rename_ms + dir_fsync_ms
#            if total_ms:  # Log if save took more than 10ms
#                file_status = "new" if not file_exists else "update"
#                logger.trace(
#                    f"Save timing breakdown ({total_ms:.1f}ms total, {file_status}): "
#                    f"serialize={serialize_ms:.1f}ms, write={write_ms:.1f}ms, "
#                    f"file_fsync={file_fsync_ms:.1f}ms, rename={rename_ms:.1f}ms, "
#                    f"dir_fsync={dir_fsync_ms:.1f}ms, using_orjson={HAS_ORJSON}"
#                )

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

    finally:
        # Always release lock and close lock file
        try:
            _unlock_file(lock_file)
        except:
            pass  # Lock might not have been acquired
        try:
            lock_file.close()
        except:
            pass


def save_watch_atomic(watch_dir, uuid, watch_dict):
    """
    Save a watch to disk using atomic write pattern.

    Convenience wrapper around save_json_atomic for watches.

    Args:
        watch_dir: Directory for this watch (e.g., /datastore/{uuid})
        uuid: Watch UUID (for logging)
        watch_dict: Dictionary representation of the watch

    Raises:
        ValueError: If serialized data exceeds 10MB (indicates bug or corruption)
        OSError: If disk is full (ENOSPC) or other I/O error
    """
    watch_json = os.path.join(watch_dir, "watch.json")
    save_json_atomic(watch_json, watch_dict, label=f"watch {uuid}", max_size_mb=10)


def load_watch_from_file(watch_json, uuid, rehydrate_entity_func):
    """
    Load a watch from its JSON file.

    Args:
        watch_json: Path to the watch.json file
        uuid: Watch UUID
        rehydrate_entity_func: Function to convert dict to Watch object

    Returns:
        Tuple of (Watch object, raw_data_dict) or (None, None) if failed
        The raw_data_dict is needed to compute the hash before rehydration
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
            return None, None

        if HAS_ORJSON:
            with open(watch_json, 'rb') as f:
                watch_data = orjson.loads(f.read())
        else:
            with open(watch_json, 'r', encoding='utf-8') as f:
                watch_data = json.load(f)

        # Return both the raw data and the rehydrated watch
        # Raw data is needed to compute hash before rehydration changes anything
        watch_obj = rehydrate_entity_func(uuid, watch_data)
        return watch_obj, watch_data

    except json.JSONDecodeError as e:
        logger.critical(
            f"CORRUPTED WATCH DATA: Failed to parse JSON for watch {uuid}. "
            f"File: {watch_json}. Error: {e}. "
            f"Watch will be skipped and may need manual recovery from backup."
        )
        return None, None
    except ValueError as e:
        # orjson raises ValueError for invalid JSON
        if "invalid json" in str(e).lower() or HAS_ORJSON:
            logger.critical(
                f"CORRUPTED WATCH DATA: Failed to parse JSON for watch {uuid}. "
                f"File: {watch_json}. Error: {e}. "
                f"Watch will be skipped and may need manual recovery from backup."
            )
            return None, None
        # Re-raise if it's not a JSON parsing error
        raise
    except FileNotFoundError:
        logger.error(f"Watch file not found: {watch_json} for watch {uuid}")
        return None, None
    except Exception as e:
        logger.error(f"Failed to load watch {uuid} from {watch_json}: {e}")
        return None, None


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
        watch, raw_data = load_watch_from_file(watch_json, uuid_dir, rehydrate_entity_func)
        if watch and raw_data:
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


