"""
Unit tests for Huey FileStorage task manager.

Tests the basic functionality of the FileStorage task manager without requiring
a full Huey instance or changedetection.io app.
"""

import pytest
import tempfile
import shutil
import os
from changedetectionio.notification.task_queue.file_storage import FileStorageTaskManager


class MockStorage:
    """Mock storage object to simulate Huey FileStorage."""
    def __init__(self, path):
        self.path = path


@pytest.fixture
def temp_storage_dir():
    """Create a temporary directory for testing."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def task_manager(temp_storage_dir):
    """Create a FileStorageTaskManager instance for testing."""
    mock_storage = MockStorage(temp_storage_dir)
    return FileStorageTaskManager(mock_storage, temp_storage_dir)


class TestFileStorageTaskManager:
    """Tests for FileStorageTaskManager basic functionality."""

    def test_store_and_get_metadata(self, task_manager):
        """Test storing and retrieving task metadata."""
        task_id = "test-task-123"
        # Use realistic notification data structure matching actual app usage
        metadata = {
            'notification_data': {
                'watch_url': 'https://example.com/test',
                'uuid': 'test-watch-uuid-123',
                'current_snapshot': 'Test content snapshot',
                'diff': '+ New content added\n- Old content removed',
                'diff_clean': 'New content added\nOld content removed',
                'triggered_text': 'price: $99.99',
                'notification_urls': ['mailto://test@example.com'],
                'notification_title': 'Change detected on example.com',
                'notification_body': 'The page has changed',
                'notification_format': 'HTML'
            }
        }

        # Store metadata
        result = task_manager.store_task_metadata(task_id, metadata)
        assert result is True, "Should successfully store metadata"

        # Retrieve metadata
        retrieved = task_manager.get_task_metadata(task_id)
        assert retrieved is not None, "Should retrieve stored metadata"
        assert retrieved['task_id'] == task_id
        assert 'timestamp' in retrieved
        assert retrieved['notification_data'] == metadata['notification_data']

    def test_delete_metadata(self, task_manager):
        """Test deleting task metadata."""
        task_id = "test-task-456"
        metadata = {'notification_data': {'test': 'data'}}

        # Store then delete
        task_manager.store_task_metadata(task_id, metadata)
        result = task_manager.delete_task_metadata(task_id)
        assert result is True, "Should successfully delete metadata"

        # Verify it's gone
        retrieved = task_manager.get_task_metadata(task_id)
        assert retrieved is None, "Metadata should be deleted"

    def test_delete_nonexistent_metadata(self, task_manager):
        """Test deleting metadata that doesn't exist."""
        result = task_manager.delete_task_metadata("nonexistent-task")
        assert result is False, "Should return False for nonexistent metadata"

    def test_get_nonexistent_metadata(self, task_manager):
        """Test retrieving metadata that doesn't exist."""
        retrieved = task_manager.get_task_metadata("nonexistent-task")
        assert retrieved is None, "Should return None for nonexistent metadata"

    def test_count_storage_items_empty(self, task_manager):
        """Test counting storage items when empty."""
        queue_count, schedule_count = task_manager.count_storage_items()
        assert queue_count == 0, "Empty queue should have 0 items"
        assert schedule_count == 0, "Empty schedule should have 0 items"

    def test_count_storage_items_with_files(self, task_manager, temp_storage_dir):
        """Test counting storage items with files present."""
        # Create some queue files
        queue_dir = os.path.join(temp_storage_dir, 'queue')
        os.makedirs(queue_dir, exist_ok=True)

        for i in range(3):
            with open(os.path.join(queue_dir, f"task-{i}"), 'w') as f:
                f.write("test")

        # Create some schedule files
        schedule_dir = os.path.join(temp_storage_dir, 'schedule')
        os.makedirs(schedule_dir, exist_ok=True)

        for i in range(2):
            with open(os.path.join(schedule_dir, f"scheduled-{i}"), 'w') as f:
                f.write("test")

        queue_count, schedule_count = task_manager.count_storage_items()
        assert queue_count == 3, "Should count 3 queue items"
        assert schedule_count == 2, "Should count 2 schedule items"

    def test_clear_all_notifications(self, task_manager, temp_storage_dir):
        """Test clearing all notifications."""
        # Create test files in various directories
        for subdir in ['queue', 'schedule', 'results']:
            dir_path = os.path.join(temp_storage_dir, subdir)
            os.makedirs(dir_path, exist_ok=True)
            with open(os.path.join(dir_path, 'test-file'), 'w') as f:
                f.write("test")

        # Create metadata files
        metadata_dir = os.path.join(temp_storage_dir, 'task_metadata')
        os.makedirs(metadata_dir, exist_ok=True)
        with open(os.path.join(metadata_dir, 'test-task.json'), 'w') as f:
            f.write('{"test": "data"}')

        # Clear all
        cleared = task_manager.clear_all_notifications()

        assert cleared['queue'] == 1, "Should clear 1 queue file"
        assert cleared['schedule'] == 1, "Should clear 1 schedule file"
        assert cleared['results'] == 1, "Should clear 1 result file"
        assert cleared['task_metadata'] == 1, "Should clear 1 metadata file"

    def test_metadata_file_structure(self, task_manager, temp_storage_dir):
        """Test that metadata files are created in the correct structure."""
        task_id = "test-structure-789"
        metadata = {'notification_data': {'test': 'value'}}

        task_manager.store_task_metadata(task_id, metadata)

        # Check file exists in correct location
        expected_path = os.path.join(temp_storage_dir, 'task_metadata', f"{task_id}.json")
        assert os.path.exists(expected_path), f"Metadata file should exist at {expected_path}"

        # Check file contains valid JSON
        import json
        with open(expected_path, 'r') as f:
            data = json.load(f)
            assert data['task_id'] == task_id
            assert 'timestamp' in data
            assert 'notification_data' in data
