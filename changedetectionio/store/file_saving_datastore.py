"""
File-based datastore with individual watch persistence and dirty tracking.

This module provides the FileSavingDataStore abstract class that implements:
- Individual watch.json file persistence
- Hash-based change detection (only save what changed)
- Background save thread with dirty tracking
- Atomic file writes safe for NFS/NAS
"""

import glob
import hashlib
import json
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from distutils.util import strtobool
from threading import Thread
from loguru import logger

from .base import DataStore

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
        total_ms = serialize_ms + write_ms + file_fsync_ms + rename_ms + dir_fsync_ms
        if total_ms:  # Log if save took more than 10ms
            file_status = "new" if not file_exists else "update"
            logger.debug(
                f"Save timing breakdown ({total_ms:.1f}ms total, {file_status}): "
                f"serialize={serialize_ms:.1f}ms, write={write_ms:.1f}ms, "
                f"file_fsync={file_fsync_ms:.1f}ms, rename={rename_ms:.1f}ms, "
                f"dir_fsync={dir_fsync_ms:.1f}ms, using_orjson={HAS_ORJSON}"
            )

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


def load_all_watches(datastore_path, rehydrate_entity_func, compute_hash_func):
    """
    Load all watches from individual watch.json files.

    SYNCHRONOUS loading: Blocks until all watches are loaded.
    This ensures data consistency - web server won't accept requests
    until all watches are available. Progress logged every 100 watches.

    Args:
        datastore_path: Path to the datastore directory
        rehydrate_entity_func: Function to convert dict to Watch object
        compute_hash_func: Function to compute hash from raw watch dict

    Returns:
        Tuple of (watching_dict, hashes_dict)
        - watching_dict: uuid -> Watch object
        - hashes_dict: uuid -> hash string (computed from raw data)
    """
    start_time = time.time()
    logger.info("Loading watches from individual watch.json files...")

    watching = {}
    watch_hashes = {}

    if not os.path.exists(datastore_path):
        return watching, watch_hashes

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
            # Compute hash from raw data BEFORE rehydration to match saved hash
            watch_hashes[uuid_dir] = compute_hash_func(raw_data)
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

    return watching, watch_hashes


# ============================================================================
# FileSavingDataStore Class
# ============================================================================

class FileSavingDataStore(DataStore):
    """
    Abstract datastore that provides file persistence with change tracking.

    Features:
    - Individual watch.json files (one per watch)
    - Dirty tracking: Only saves items that have changed
    - Hash-based change detection: Prevents unnecessary writes
    - Background save thread: Non-blocking persistence
    - Two-tier urgency: Standard (60s) and urgent (immediate) saves

    Subclasses must implement:
    - rehydrate_entity(): Convert dict to Watch object
    - Access to internal __data structure for watch management
    """

    needs_write = False
    needs_write_urgent = False
    stop_thread = False

    # Change tracking
    _dirty_watches = set()      # Watch UUIDs that need saving
    _dirty_settings = False     # Settings changed
    _watch_hashes = {}          # UUID -> SHA256 hash for change detection

    # Health monitoring
    _last_save_time = 0         # Timestamp of last successful save
    _save_cycle_count = 0       # Number of save cycles completed
    _total_saves = 0            # Total watches saved (lifetime)
    _save_errors = 0            # Total save errors (lifetime)

    def __init__(self):
        super().__init__()
        self.save_data_thread = None
        self._last_save_time = time.time()

    def _compute_hash(self, watch_dict):
        """
        Compute SHA256 hash of watch for change detection.

        Args:
            watch_dict: Dictionary representation of watch

        Returns:
            Hex string of SHA256 hash
        """
        # Use orjson for deterministic serialization if available
        if HAS_ORJSON:
            json_bytes = orjson.dumps(watch_dict, option=orjson.OPT_SORT_KEYS)
        else:
            json_str = json.dumps(watch_dict, sort_keys=True, ensure_ascii=False)
            json_bytes = json_str.encode('utf-8')

        return hashlib.sha256(json_bytes).hexdigest()

    def mark_watch_dirty(self, uuid):
        """
        Mark a watch as needing save.

        Args:
            uuid: Watch UUID
        """
        with self.lock:
            self._dirty_watches.add(uuid)
            dirty_count = len(self._dirty_watches)

        # Backpressure detection - warn if dirty set grows too large
        if dirty_count > 1000:
            logger.critical(
                f"BACKPRESSURE WARNING: {dirty_count} watches pending save! "
                f"Save thread may not be keeping up with write rate. "
                f"This could indicate disk I/O bottleneck or save thread failure."
            )
        elif dirty_count > 500:
            logger.warning(
                f"Dirty watch count high: {dirty_count} watches pending save. "
                f"Monitoring for potential backpressure."
            )

        self.needs_write = True

    def mark_settings_dirty(self):
        """Mark settings as needing save."""
        with self.lock:
            self._dirty_settings = True
        self.needs_write = True

    def save_watch(self, uuid, force=False, watch_dict=None, current_hash=None):
        """
        Save a single watch if it has changed (polymorphic method).

        This is the high-level save method that handles:
        - Hash computation and change detection
        - Calling the backend-specific save implementation
        - Updating the hash cache

        Args:
            uuid: Watch UUID
            force: If True, skip hash check and save anyway
            watch_dict: Pre-computed watch dictionary (optimization to avoid redundant serialization)
            current_hash: Pre-computed hash (optimization to avoid redundant hashing)

        Returns:
            True if saved, False if skipped (unchanged)
        """
        if not self._watch_exists(uuid):
            logger.warning(f"Cannot save watch {uuid} - does not exist")
            return False

        # Use pre-computed values if provided (avoids redundant work)
        if watch_dict is None:
            watch_dict = self._get_watch_dict(uuid)
        if current_hash is None:
            current_hash = self._compute_hash(watch_dict)

        # Skip save if unchanged (unless forced)
        if not force and current_hash == self._watch_hashes.get(uuid):
            #logger.debug(f"Watch {uuid} unchanged, skipping save")
            return False

        try:
            self._save_watch(uuid, watch_dict)
            self._watch_hashes[uuid] = current_hash
            logger.debug(f"Saved watch {uuid}")
            return True
        except Exception as e:
            logger.error(f"Failed to save watch {uuid}: {e}")
            raise

    def _save_watch(self, uuid, watch_dict):
        """
        Save a single watch to storage (polymorphic).

        Backend-specific implementation. Subclasses override for different storage:
        - File backend: Writes to {uuid}/watch.json
        - Redis backend: SET watch:{uuid}
        - SQL backend: UPDATE watches WHERE uuid=?

        Args:
            uuid: Watch UUID
            watch_dict: Dictionary representation of watch
        """
        # Default file implementation
        watch_dir = os.path.join(self.datastore_path, uuid)
        save_watch_atomic(watch_dir, uuid, watch_dict)

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

    def _save_dirty_items(self):
        """
        Save only items that have changed.

        This is the core optimization: instead of saving the entire datastore,
        we only save watches that were marked dirty and settings if changed.
        """
        start_time = time.time()

        # Capture dirty sets under lock
        with self.lock:
            dirty_watches = list(self._dirty_watches)
            dirty_settings = self._dirty_settings
            self._dirty_watches.clear()
            self._dirty_settings = False

        if not dirty_watches and not dirty_settings:
            return

        logger.debug(f"Checking {len(dirty_watches)} dirty watches, settings_dirty={dirty_settings}")

        # Save each dirty watch using the polymorphic save method
        saved_count = 0
        error_count = 0
        skipped_unchanged = 0

        # Process in batches of 50, using thread pool for parallel saves
        BATCH_SIZE = 50
        MAX_WORKERS = 20  # Number of parallel save threads

        def save_single_watch(uuid):
            """Helper function for thread pool execution."""
            try:
                # Check if watch still exists (might have been deleted)
                if not self._watch_exists(uuid):
                    # Watch was deleted, remove hash
                    self._watch_hashes.pop(uuid, None)
                    return {'status': 'deleted', 'uuid': uuid}

                # Pre-check hash to avoid unnecessary save_watch() calls
                watch_dict = self._get_watch_dict(uuid)
                current_hash = self._compute_hash(watch_dict)

                if current_hash == self._watch_hashes.get(uuid):
                    # Watch hasn't actually changed, skip
                    return {'status': 'unchanged', 'uuid': uuid}

                # Pass pre-computed values to avoid redundant serialization/hashing
                if self.save_watch(uuid, force=True, watch_dict=watch_dict, current_hash=current_hash):
                    return {'status': 'saved', 'uuid': uuid}
                else:
                    return {'status': 'skipped', 'uuid': uuid}
            except Exception as e:
                logger.error(f"Error saving watch {uuid}: {e}")
                return {'status': 'error', 'uuid': uuid, 'error': e}

        # Process dirty watches in batches
        for batch_start in range(0, len(dirty_watches), BATCH_SIZE):
            batch = dirty_watches[batch_start:batch_start + BATCH_SIZE]
            batch_num = (batch_start // BATCH_SIZE) + 1
            total_batches = (len(dirty_watches) + BATCH_SIZE - 1) // BATCH_SIZE

            if len(dirty_watches) > BATCH_SIZE:
                logger.debug(f"Processing batch {batch_num}/{total_batches} ({len(batch)} watches)")

            # Use thread pool to save watches in parallel
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                # Submit all save tasks
                future_to_uuid = {executor.submit(save_single_watch, uuid): uuid for uuid in batch}

                # Collect results as they complete
                for future in as_completed(future_to_uuid):
                    result = future.result()
                    status = result['status']

                    if status == 'saved':
                        saved_count += 1
                    elif status == 'unchanged':
                        skipped_unchanged += 1
                    elif status == 'error':
                        error_count += 1
                        # Re-mark for retry
                        with self.lock:
                            self._dirty_watches.add(result['uuid'])
                    # 'deleted' and 'skipped' don't need special handling

        # Save settings if changed
        if dirty_settings:
            try:
                self._save_settings()
                logger.debug("Saved settings")
            except Exception as e:
                logger.error(f"Failed to save settings: {e}")
                error_count += 1
                with self.lock:
                    self._dirty_settings = True

        # Update metrics
        elapsed = time.time() - start_time
        self._save_cycle_count += 1
        self._total_saves += saved_count
        self._save_errors += error_count
        self._last_save_time = time.time()

        # Log performance metrics
        if saved_count > 0:
            avg_time_per_watch = (elapsed / saved_count) * 1000  # milliseconds
            skipped_msg = f", {skipped_unchanged} unchanged" if skipped_unchanged > 0 else ""
            parallel_msg = f" [parallel: {MAX_WORKERS} workers]" if saved_count > 1 else ""
            logger.info(
                f"Successfully saved {saved_count} watches in {elapsed:.2f}s "
                f"(avg {avg_time_per_watch:.1f}ms per watch{skipped_msg}){parallel_msg}. "
                f"Total: {self._total_saves} saves, {self._save_errors} errors (lifetime)"
            )
        elif skipped_unchanged > 0:
            logger.debug(f"Save cycle: {skipped_unchanged} watches unchanged, nothing saved")

        if error_count > 0:
            logger.error(f"Save cycle completed with {error_count} errors")

        self.needs_write = False
        self.needs_write_urgent = False

    def _watch_exists(self, uuid):
        """
        Check if watch exists. Subclass must implement.

        Args:
            uuid: Watch UUID

        Returns:
            bool
        """
        raise NotImplementedError("Subclass must implement _watch_exists")

    def _get_watch_dict(self, uuid):
        """
        Get watch as dictionary. Subclass must implement.

        Args:
            uuid: Watch UUID

        Returns:
            Dictionary representation of watch
        """
        raise NotImplementedError("Subclass must implement _get_watch_dict")

    def save_datastore(self):
        """
        Background thread that periodically saves dirty items.

        Runs every 60 seconds (with 0.5s sleep intervals for responsiveness),
        or immediately when needs_write_urgent is set.
        """
        while True:
            if self.stop_thread:
                # Graceful shutdown: flush any remaining dirty items before stopping
                if self.needs_write or self._dirty_watches or self._dirty_settings:
                    logger.warning("Datastore save thread stopping - flushing remaining dirty items...")
                    try:
                        self._save_dirty_items()
                        logger.info("Graceful shutdown complete - all data saved")
                    except Exception as e:
                        logger.critical(f"FAILED to save dirty items during shutdown: {e}")
                else:
                    logger.info("Datastore save thread stopping - no dirty items")
                return

            if self.needs_write or self.needs_write_urgent:
                try:
                    self._save_dirty_items()
                except Exception as e:
                    logger.error(f"Error in save cycle: {e}")

            # 60 second timer with early break for urgent saves
            for i in range(120):
                time.sleep(0.5)
                if self.stop_thread or self.needs_write_urgent:
                    break

    def start_save_thread(self):
        """Start the background save thread."""
        if not self.save_data_thread or not self.save_data_thread.is_alive():
            self.save_data_thread = Thread(target=self.save_datastore, daemon=True, name="DatastoreSaver")
            self.save_data_thread.start()
            logger.info("Datastore save thread started")

    def force_save_all(self):
        """
        Force immediate synchronous save of all changes to storage.

        File backend implementation of the abstract force_save_all() method.
        Marks all watches and settings as dirty, then saves immediately.

        Used by:
        - Backup creation (ensure everything is saved before backup)
        - Shutdown (ensure all changes are persisted)
        - Manual save operations
        """
        logger.info("Force saving all data to storage...")

        # Mark everything as dirty to ensure complete save
        for uuid in self.data['watching'].keys():
            self.mark_watch_dirty(uuid)
        self.mark_settings_dirty()

        # Save immediately (synchronous)
        self._save_dirty_items()

        logger.success("All data saved to storage")

    def get_health_status(self):
        """
        Get datastore health status for monitoring.

        Returns:
            dict with health metrics and status
        """
        now = time.time()
        time_since_last_save = now - self._last_save_time

        with self.lock:
            dirty_count = len(self._dirty_watches)

        is_thread_alive = self.save_data_thread and self.save_data_thread.is_alive()

        # Determine health status
        if not is_thread_alive:
            status = "CRITICAL"
            message = "Save thread is DEAD"
        elif time_since_last_save > 300:  # 5 minutes
            status = "WARNING"
            message = f"No save activity for {time_since_last_save:.0f}s"
        elif dirty_count > 1000:
            status = "WARNING"
            message = f"High backpressure: {dirty_count} watches pending"
        elif self._save_errors > 0 and (self._save_errors / max(self._total_saves, 1)) > 0.01:
            status = "WARNING"
            message = f"High error rate: {self._save_errors} errors"
        else:
            status = "HEALTHY"
            message = "Operating normally"

        return {
            "status": status,
            "message": message,
            "thread_alive": is_thread_alive,
            "dirty_watches": dirty_count,
            "dirty_settings": self._dirty_settings,
            "last_save_seconds_ago": int(time_since_last_save),
            "save_cycles": self._save_cycle_count,
            "total_saves": self._total_saves,
            "total_errors": self._save_errors,
            "error_rate_percent": round((self._save_errors / max(self._total_saves, 1)) * 100, 2)
        }
