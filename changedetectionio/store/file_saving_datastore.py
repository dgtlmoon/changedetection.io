"""
File-based datastore with individual watch persistence and dirty tracking.

This module provides the FileSavingDataStore abstract class that implements:
- Individual watch.json file persistence
- Hash-based change detection (only save what changed)
- Background save thread with dirty tracking
- Atomic file writes safe for NFS/NAS
"""

import hashlib
import json
import os
import tempfile
import time
from threading import Thread
from loguru import logger

from .base import DataStore

# Try to import orjson for faster JSON serialization
try:
    import orjson
    HAS_ORJSON = True
except ImportError:
    HAS_ORJSON = False


# ============================================================================
# Helper Functions for Atomic File Operations
# ============================================================================

def save_json_atomic(file_path, data_dict, label="file", max_size_mb=10):
    """
    Save JSON data to disk using atomic write pattern.

    Generic helper for saving any JSON data (settings, watches, etc.) with:
    - Atomic write (temp file + rename)
    - Directory fsync for crash consistency
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
        if HAS_ORJSON:
            data = orjson.dumps(data_dict, option=orjson.OPT_INDENT_2)
        else:
            data = json.dumps(data_dict, indent=2, ensure_ascii=False).encode('utf-8')

        # Safety check: validate size
        MAX_SIZE = max_size_mb * 1024 * 1024
        data_size = len(data)
        if data_size > MAX_SIZE:
            raise ValueError(
                f"{label.capitalize()} data is unexpectedly large: {data_size / 1024 / 1024:.2f}MB "
                f"(max: {max_size_mb}MB). This indicates a bug or data corruption."
            )

        # Write to temp file
        os.write(fd, data)
        os.fsync(fd)  # Force file data to disk
        os.close(fd)
        fd_closed = True

        # Atomic rename
        os.replace(temp_path, file_path)

        # Sync directory to ensure filename metadata is durable
        try:
            dir_fd = os.open(parent_dir, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except (OSError, AttributeError):
            # Windows doesn't support fsync on directories
            pass

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
    logger.info("Loading watches from individual watch.json files...")

    watching = {}
    watch_hashes = {}

    # Find all UUID directories
    if not os.path.exists(datastore_path):
        return watching, watch_hashes

    # Get all directories that look like UUIDs
    try:
        all_items = os.listdir(datastore_path)
    except Exception as e:
        logger.error(f"Failed to list datastore directory: {e}")
        return watching, watch_hashes

    uuid_dirs = [
        d for d in all_items
        if os.path.isdir(os.path.join(datastore_path, d))
        and not d.startswith('.')  # Skip hidden dirs
        and d not in ['__pycache__']  # Skip Python cache dirs
    ]

    # First pass: count directories with watch.json files
    watch_dirs = []
    for uuid_dir in uuid_dirs:
        watch_json = os.path.join(datastore_path, uuid_dir, "watch.json")
        if os.path.isfile(watch_json):
            watch_dirs.append(uuid_dir)

    total = len(watch_dirs)
    loaded = 0
    failed = 0

    for uuid_dir in watch_dirs:
        watch_json = os.path.join(datastore_path, uuid_dir, "watch.json")
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

    if failed > 0:
        logger.critical(
            f"LOAD COMPLETE: {loaded} watches loaded successfully, "
            f"{failed} watches FAILED to load (corrupted or invalid)"
        )
    else:
        logger.info(f"Loaded {loaded} watches from disk")

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

    def save_watch(self, uuid, force=False):
        """
        Save a single watch if it has changed (polymorphic method).

        This is the high-level save method that handles:
        - Hash computation and change detection
        - Calling the backend-specific save implementation
        - Updating the hash cache

        Args:
            uuid: Watch UUID
            force: If True, skip hash check and save anyway

        Returns:
            True if saved, False if skipped (unchanged)
        """
        if not self._watch_exists(uuid):
            logger.warning(f"Cannot save watch {uuid} - does not exist")
            return False

        watch_dict = self._get_watch_dict(uuid)
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

        for uuid in dirty_watches:
            # Check if watch still exists (might have been deleted)
            if not self._watch_exists(uuid):
                # Watch was deleted, remove hash
                self._watch_hashes.pop(uuid, None)
                continue

            # Pre-check hash to avoid unnecessary save_watch() calls
            watch_dict = self._get_watch_dict(uuid)
            current_hash = self._compute_hash(watch_dict)

            if current_hash == self._watch_hashes.get(uuid):
                # Watch hasn't actually changed, skip
                skipped_unchanged += 1
                continue

            try:
                if self.save_watch(uuid, force=True):  # force=True since we already checked hash
                    saved_count += 1
            except Exception as e:
                error_count += 1
                # Re-mark for retry
                with self.lock:
                    self._dirty_watches.add(uuid)

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
            logger.info(
                f"Successfully saved {saved_count} watches in {elapsed:.2f}s "
                f"(avg {avg_time_per_watch:.1f}ms per watch{skipped_msg}). "
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
