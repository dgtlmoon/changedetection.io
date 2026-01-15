"""
File utility functions for atomic JSON operations.

Provides safe, atomic file operations for storing retry attempts
and delivered notification confirmations.
"""

import os
import json
import tempfile
from loguru import logger


def _atomic_json_write(filepath, data):
    """
    Atomically write JSON data to a file.

    Uses a temp file + rename pattern to ensure atomicity.
    This prevents corruption if the process is interrupted during write.

    Args:
        filepath: Destination file path
        data: Data to serialize as JSON

    Raises:
        IOError: If write fails
    """
    directory = os.path.dirname(filepath)

    # Create a temporary file in the same directory as the target
    # (ensures it's on the same filesystem for atomic rename)
    fd, temp_path = tempfile.mkstemp(
        dir=directory,
        prefix='.tmp_',
        suffix='.json'
    )

    try:
        # Write to temp file
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2)

        # Atomically replace the target file
        os.replace(temp_path, filepath)

    except Exception as e:
        # Clean up temp file on error
        try:
            os.unlink(temp_path)
        except:
            pass
        raise IOError(f"Failed to write {filepath}: {e}")


def _safe_json_load(filepath, data_type, storage_path):
    """
    Safely load JSON data from a file with corruption handling.

    Args:
        filepath: Path to JSON file
        data_type: Type of data for logging (e.g., 'retry_attempts', 'success')
        storage_path: Base storage path for moving corrupted files

    Returns:
        dict: Loaded JSON data, or None if file is corrupted/unreadable
    """
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.warning(f"Corrupted {data_type} file {filepath}: {e}")

        # Move corrupted file to quarantine
        try:
            quarantine_dir = os.path.join(storage_path, 'corrupted')
            os.makedirs(quarantine_dir, exist_ok=True)

            corrupted_filename = f"corrupted_{os.path.basename(filepath)}"
            quarantine_path = os.path.join(quarantine_dir, corrupted_filename)

            os.rename(filepath, quarantine_path)
            logger.info(f"Moved corrupted {data_type} file to {quarantine_path}")
        except Exception as move_error:
            logger.error(f"Could not quarantine corrupted file: {move_error}")

        return None
    except Exception as e:
        logger.debug(f"Error loading {data_type} file {filepath}: {e}")
        return None
