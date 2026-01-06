"""
FileStorage backend task manager for Huey notifications.

This is the default backend, optimized for NAS/CIFS compatibility.
"""

from loguru import logger

from .base import HueyTaskManager

import os

class FileStorageTaskManager(HueyTaskManager):
    """Task manager for FileStorage backend (default, NAS-safe)."""

    def enumerate_results(self):
        """Enumerate results by walking filesystem directories."""
        import os
        import pickle
        import struct
        import time

        results = {}

        if not self.storage_path:
            return results

        results_dir = os.path.join(self.storage_path, 'results')

        if not os.path.exists(results_dir):
            return results

        # Walk through all subdirectories to find result files
        for root, dirs, files in os.walk(results_dir):
            for filename in files:
                if filename.startswith('.'):
                    continue

                filepath = os.path.join(root, filename)
                try:
                    # Read and unpickle the result
                    # Huey FileStorage format: 4-byte length + task_id + pickled data
                    with open(filepath, 'rb') as f:
                        # Read the task ID header (length-prefixed)
                        task_id_len_bytes = f.read(4)
                        if len(task_id_len_bytes) < 4:
                            raise EOFError("Incomplete header")
                        task_id_len = struct.unpack('>I', task_id_len_bytes)[0]
                        task_id_bytes = f.read(task_id_len)
                        if len(task_id_bytes) < task_id_len:
                            raise EOFError("Incomplete task ID")
                        task_id = task_id_bytes.decode('utf-8')

                        # Now unpickle the result data
                        result_data = pickle.load(f)
                        results[task_id] = result_data
                except (pickle.UnpicklingError, EOFError) as e:
                    # Corrupted or incomplete result file
                    file_size = os.path.getsize(filepath)
                    logger.warning(f"Corrupted result file {filename} ({file_size} bytes) - moving to lost-found.")
                    try:
                        import shutil
                        lost_found_dir = os.path.join(self.storage_path, 'lost-found', 'results')
                        os.makedirs(lost_found_dir, exist_ok=True)

                        timestamp = int(time.time())
                        lost_found_path = os.path.join(lost_found_dir, f"{filename}.{timestamp}.corrupted")

                        shutil.move(filepath, lost_found_path)
                        logger.info(f"Moved corrupted file to {lost_found_path}")
                    except Exception as move_err:
                        logger.error(f"Unable to move corrupted file: {move_err}")
                except Exception as e:
                    logger.debug(f"Unable to read result file {filename}: {e}")

        return results

    def delete_result(self, task_id):
        """Delete result file from filesystem."""
        import hashlib

        if not self.storage_path:
            return False

        results_dir = os.path.join(self.storage_path, 'results')

        # Huey uses MD5 hash to create subdirectories
        task_id_bytes = task_id.encode('utf-8')
        hex_hash = hashlib.md5(task_id_bytes).hexdigest()

        # FileStorage creates subdirectories based on first 2 chars of hash
        subdir = hex_hash[:2]
        result_file = os.path.join(results_dir, subdir, task_id)

        if os.path.exists(result_file):
            os.remove(result_file)
            logger.debug(f"Deleted result file for task {task_id}")
            return True
        else:
            logger.debug(f"Result file not found for task {task_id}")
            return False

    def count_storage_items(self):
        """Count items by walking filesystem directories."""
        queue_count = 0
        schedule_count = 0

        if not self.storage_path:
            return queue_count, schedule_count

        try:
            # Count queue files
            queue_dir = os.path.join(self.storage_path, 'queue')
            if os.path.exists(queue_dir):
                for root, dirs, files in os.walk(queue_dir):
                    queue_count += len([f for f in files if not f.startswith('.')])

            # Count schedule files
            schedule_dir = os.path.join(self.storage_path, 'schedule')
            if os.path.exists(schedule_dir):
                for root, dirs, files in os.walk(schedule_dir):
                    schedule_count += len([f for f in files if not f.startswith('.')])
        except Exception as e:
            logger.debug(f"FileStorage count error: {e}")

        return queue_count, schedule_count

    def clear_all_notifications(self):
        """Clear all notification files from filesystem."""
        cleared = {
            'queue': 0,
            'schedule': 0,
            'results': 0,
            'retry_attempts': 0,
            'task_metadata': 0,
            'delivered': 0
        }

        if not self.storage_path:
            return cleared

        # Clear queue
        queue_dir = os.path.join(self.storage_path, 'queue')
        if os.path.exists(queue_dir):
            for root, dirs, files in os.walk(queue_dir):
                for f in files:
                    if not f.startswith('.'):
                        os.remove(os.path.join(root, f))
                        cleared['queue'] += 1

        # Clear schedule
        schedule_dir = os.path.join(self.storage_path, 'schedule')
        if os.path.exists(schedule_dir):
            for root, dirs, files in os.walk(schedule_dir):
                for f in files:
                    if not f.startswith('.'):
                        os.remove(os.path.join(root, f))
                        cleared['schedule'] += 1

        # Clear results
        results_dir = os.path.join(self.storage_path, 'results')
        if os.path.exists(results_dir):
            for root, dirs, files in os.walk(results_dir):
                for f in files:
                    if not f.startswith('.'):
                        os.remove(os.path.join(root, f))
                        cleared['results'] += 1

        # Clear retry attempts
        attempts_dir = os.path.join(self.storage_path, 'retry_attempts')
        if os.path.exists(attempts_dir):
            for f in os.listdir(attempts_dir):
                if f.endswith('.json'):
                    os.remove(os.path.join(attempts_dir, f))
                    cleared['retry_attempts'] += 1

        # Clear task metadata
        metadata_dir = os.path.join(self.storage_path, 'task_metadata')
        if os.path.exists(metadata_dir):
            for f in os.listdir(metadata_dir):
                if f.endswith('.json'):
                    os.remove(os.path.join(metadata_dir, f))
                    cleared['task_metadata'] += 1

        # Clear delivered (success) notifications
        success_dir = os.path.join(self.storage_path, 'success')
        if os.path.exists(success_dir):
            for f in os.listdir(success_dir):
                if f.startswith('success-') and f.endswith('.json'):
                    os.remove(os.path.join(success_dir, f))
                    cleared['delivered'] += 1

        return cleared

    def store_task_metadata(self, task_id, metadata):
        """Store task metadata as JSON file."""
        import json
        import time

        if not self.storage_path:
            return False

        try:
            metadata_dir = os.path.join(self.storage_path, 'task_metadata')
            os.makedirs(metadata_dir, exist_ok=True)

            metadata_file = os.path.join(metadata_dir, f"{task_id}.json")
            metadata_with_id = {
                'task_id': task_id,
                'timestamp': time.time(),
                **metadata
            }

            with open(metadata_file, 'w') as f:
                json.dump(metadata_with_id, f, indent=2)
            return True
        except Exception as e:
            logger.debug(f"Unable to store task metadata: {e}")
            return False

    def get_task_metadata(self, task_id):
        """Retrieve task metadata from JSON file."""
        import json

        if not self.storage_path:
            return None

        try:
            metadata_dir = os.path.join(self.storage_path, 'task_metadata')
            metadata_file = os.path.join(metadata_dir, f"{task_id}.json")

            if os.path.exists(metadata_file):
                with open(metadata_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.debug(f"Unable to load task metadata for {task_id}: {e}")

        return None

    def delete_task_metadata(self, task_id):
        """Delete task metadata JSON file."""
        if not self.storage_path:
            return False

        try:
            metadata_dir = os.path.join(self.storage_path, 'task_metadata')
            metadata_file = os.path.join(metadata_dir, f"{task_id}.json")

            if os.path.exists(metadata_file):
                os.remove(metadata_file)
                return True
            return False
        except Exception as e:
            logger.debug(f"Unable to delete task metadata for {task_id}: {e}")
            return False

    def cleanup_old_retry_attempts(self, cutoff_time):
        """Clean up old retry attempt files from filesystem."""
        if not self.storage_path:
            return 0

        deleted_count = 0
        try:
            attempts_dir = os.path.join(self.storage_path, 'retry_attempts')
            if os.path.exists(attempts_dir):
                for filename in os.listdir(attempts_dir):
                    if filename.endswith('.json'):
                        filepath = os.path.join(attempts_dir, filename)
                        try:
                            file_mtime = os.path.getmtime(filepath)
                            if file_mtime < cutoff_time:
                                os.remove(filepath)
                                deleted_count += 1
                        except Exception as fe:
                            logger.debug(f"Unable to delete old retry attempt file {filename}: {fe}")
        except Exception as e:
            logger.debug(f"Error cleaning up old retry attempts: {e}")

        return deleted_count
