"""
Test suite for PostgreSQL Storage Adapter

Run with: pytest tasks/test_pg_store.py -v

Requires DATABASE_URL environment variable to be set for integration tests.
"""

import os
import pytest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

# Import the module under test
from tasks.pg_store import (
    PostgreSQLStore,
    WatchRecord,
    SnapshotRecord,
    create_watch_from_changedetection,
    SCHEMA_VERSION,
)


# =============================================================================
# Unit Tests (No Database Required)
# =============================================================================

class TestWatchRecord:
    """Tests for WatchRecord dataclass"""

    def test_create_watch_record(self):
        """Test creating a basic WatchRecord"""
        watch = WatchRecord(
            id=str(uuid.uuid4()),
            url="https://example.com",
            title="Test Watch",
            tag="test"
        )
        assert watch.url == "https://example.com"
        assert watch.title == "Test Watch"
        assert watch.tag == "test"
        assert watch.paused is False
        assert watch.check_interval == 3600

    def test_watch_record_to_dict(self):
        """Test converting WatchRecord to dictionary"""
        watch_id = str(uuid.uuid4())
        now = datetime.utcnow()
        watch = WatchRecord(
            id=watch_id,
            url="https://example.com",
            title="Test",
            created_at=now
        )
        data = watch.to_dict()

        assert data['id'] == watch_id
        assert data['url'] == "https://example.com"
        assert data['created_at'] == now.isoformat()

    def test_watch_record_from_dict(self):
        """Test creating WatchRecord from dictionary"""
        watch_id = str(uuid.uuid4())
        now = datetime.utcnow()
        data = {
            'id': watch_id,
            'url': "https://example.com",
            'title': "Test",
            'tag': "tag1",
            'check_interval': 1800,
            'last_checked': now.isoformat(),
            'last_changed': None,
            'paused': False,
            'created_at': now.isoformat(),
            'processor': 'text_json_diff',
            'fetch_backend': 'html_requests',
            'include_filters': ['div.content'],
            'headers': {'User-Agent': 'Test'},
            'notification_urls': ['slack://webhook'],
            'extra_config': {'key': 'value'}
        }
        watch = WatchRecord.from_dict(data)

        assert watch.id == watch_id
        assert watch.url == "https://example.com"
        assert watch.check_interval == 1800
        assert isinstance(watch.last_checked, datetime)


class TestSnapshotRecord:
    """Tests for SnapshotRecord dataclass"""

    def test_create_snapshot_record(self):
        """Test creating a basic SnapshotRecord"""
        snapshot = SnapshotRecord(
            id=str(uuid.uuid4()),
            watch_id=str(uuid.uuid4()),
            content_hash="abc123",
            captured_at=datetime.utcnow()
        )
        assert snapshot.content_hash == "abc123"
        assert snapshot.extracted_prices is None

    def test_snapshot_with_extracted_data(self):
        """Test SnapshotRecord with extracted price/availability data"""
        snapshot = SnapshotRecord(
            id=str(uuid.uuid4()),
            watch_id=str(uuid.uuid4()),
            content_hash="abc123",
            captured_at=datetime.utcnow(),
            extracted_prices=[
                {"price": 99.99, "currency": "USD"},
                {"price": 149.99, "currency": "USD"}
            ],
            extracted_availability="in_stock"
        )
        assert len(snapshot.extracted_prices) == 2
        assert snapshot.extracted_availability == "in_stock"


class TestCreateWatchFromChangedetection:
    """Tests for the changedetection.io data conversion function"""

    def test_basic_conversion(self):
        """Test converting basic watch data"""
        watch_data = {
            'url': 'https://tickets.example.com',
            'title': 'Concert Tickets',
            'tag': 'events',
            'paused': False,
            'processor': 'text_json_diff',
            'fetch_backend': 'html_requests'
        }
        watch_id = str(uuid.uuid4())

        result = create_watch_from_changedetection(watch_data, watch_id)

        assert result.id == watch_id
        assert result.url == 'https://tickets.example.com'
        assert result.title == 'Concert Tickets'
        assert result.tag == 'events'

    def test_time_between_check_conversion(self):
        """Test converting time_between_check to seconds"""
        watch_data = {
            'url': 'https://example.com',
            'time_between_check': {
                'weeks': 0,
                'days': 0,
                'hours': 2,
                'minutes': 30,
                'seconds': 0
            }
        }
        watch_id = str(uuid.uuid4())

        result = create_watch_from_changedetection(watch_data, watch_id)

        # 2 hours + 30 minutes = 9000 seconds
        assert result.check_interval == 9000

    def test_epoch_timestamp_conversion(self):
        """Test converting epoch timestamps"""
        now_epoch = int(datetime.utcnow().timestamp())
        watch_data = {
            'url': 'https://example.com',
            'last_checked': now_epoch,
            'date_created': now_epoch - 86400  # 1 day ago
        }
        watch_id = str(uuid.uuid4())

        result = create_watch_from_changedetection(watch_data, watch_id)

        assert result.last_checked is not None
        assert result.created_at is not None

    def test_extra_config_fields(self):
        """Test that extra config fields are preserved"""
        watch_data = {
            'url': 'https://example.com',
            'ignore_text': ['cookie banner'],
            'trigger_text': ['available now'],
            'text_should_not_be_present': ['sold out'],
            'subtractive_selectors': ['.ads'],
            'extract_text': [r'\$[\d.]+']
        }
        watch_id = str(uuid.uuid4())

        result = create_watch_from_changedetection(watch_data, watch_id)

        assert result.extra_config['ignore_text'] == ['cookie banner']
        assert result.extra_config['trigger_text'] == ['available now']


class TestContentHash:
    """Tests for content hashing"""

    def test_compute_content_hash(self):
        """Test MD5 hash computation"""
        content = "Hello, World!"
        hash1 = PostgreSQLStore.compute_content_hash(content)
        hash2 = PostgreSQLStore.compute_content_hash(content)

        assert hash1 == hash2
        assert len(hash1) == 32  # MD5 produces 32 hex chars

    def test_different_content_different_hash(self):
        """Test that different content produces different hashes"""
        hash1 = PostgreSQLStore.compute_content_hash("Content A")
        hash2 = PostgreSQLStore.compute_content_hash("Content B")

        assert hash1 != hash2


class TestPostgreSQLStoreInit:
    """Tests for PostgreSQLStore initialization"""

    def test_init_with_url(self):
        """Test initialization with explicit database URL"""
        store = PostgreSQLStore(database_url="postgresql://localhost/test")
        assert store.database_url == "postgresql://localhost/test"

    def test_init_from_env(self):
        """Test initialization from environment variable"""
        with patch.dict(os.environ, {'DATABASE_URL': 'postgresql://env-db/test'}):
            store = PostgreSQLStore()
            assert store.database_url == "postgresql://env-db/test"

    def test_init_no_url_raises(self):
        """Test that missing DATABASE_URL raises ValueError"""
        with patch.dict(os.environ, {}, clear=True):
            # Also need to remove DATABASE_URL if it exists
            os.environ.pop('DATABASE_URL', None)
            with pytest.raises(ValueError) as exc_info:
                PostgreSQLStore(database_url=None)
            assert "DATABASE_URL" in str(exc_info.value)


# =============================================================================
# Integration Tests (Require Database)
# =============================================================================

# Mark all integration tests to skip if DATABASE_URL not available
pytestmark_integration = pytest.mark.skipif(
    not os.getenv('DATABASE_URL'),
    reason="DATABASE_URL environment variable not set"
)


@pytest.fixture
async def store():
    """Create and initialize a test store"""
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        pytest.skip("DATABASE_URL not set")

    store = PostgreSQLStore(database_url)
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
def sync_store():
    """Create and initialize a synchronous test store"""
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        pytest.skip("DATABASE_URL not set")

    store = PostgreSQLStore(database_url)
    store.initialize_sync()
    yield store
    store.close_sync()


@pytest.mark.asyncio
@pytestmark_integration
class TestAsyncWatchOperations:
    """Async integration tests for watch operations"""

    async def test_add_and_get_watch(self, store):
        """Test adding and retrieving a watch"""
        watch = WatchRecord(
            id=str(uuid.uuid4()),
            url=f"https://test-{uuid.uuid4().hex[:8]}.example.com",
            title="Integration Test Watch",
            tag="integration-test"
        )

        try:
            await store.add_watch(watch)
            retrieved = await store.get_watch(watch.id)

            assert retrieved is not None
            assert retrieved.url == watch.url
            assert retrieved.title == watch.title
        finally:
            await store.delete_watch(watch.id)

    async def test_get_watch_by_url(self, store):
        """Test finding a watch by URL"""
        unique_url = f"https://unique-{uuid.uuid4().hex[:8]}.example.com"
        watch = WatchRecord(
            id=str(uuid.uuid4()),
            url=unique_url,
            title="URL Test"
        )

        try:
            await store.add_watch(watch)
            found = await store.get_watch_by_url(unique_url)

            assert found is not None
            assert found.id == watch.id
        finally:
            await store.delete_watch(watch.id)

    async def test_url_exists(self, store):
        """Test checking if URL exists"""
        unique_url = f"https://exists-{uuid.uuid4().hex[:8]}.example.com"
        watch = WatchRecord(
            id=str(uuid.uuid4()),
            url=unique_url
        )

        try:
            # Should not exist before adding
            exists_before = await store.url_exists(unique_url)
            assert exists_before is False

            await store.add_watch(watch)

            # Should exist after adding
            exists_after = await store.url_exists(unique_url)
            assert exists_after is True
        finally:
            await store.delete_watch(watch.id)

    async def test_update_watch(self, store):
        """Test updating a watch"""
        watch = WatchRecord(
            id=str(uuid.uuid4()),
            url=f"https://update-{uuid.uuid4().hex[:8]}.example.com",
            title="Original Title",
            paused=False
        )

        try:
            await store.add_watch(watch)

            # Update multiple fields
            success = await store.update_watch(watch.id, {
                'title': 'Updated Title',
                'paused': True,
                'check_interval': 7200
            })

            assert success is True

            updated = await store.get_watch(watch.id)
            assert updated.title == 'Updated Title'
            assert updated.paused is True
            assert updated.check_interval == 7200
        finally:
            await store.delete_watch(watch.id)

    async def test_delete_watch(self, store):
        """Test deleting a watch"""
        watch = WatchRecord(
            id=str(uuid.uuid4()),
            url=f"https://delete-{uuid.uuid4().hex[:8]}.example.com"
        )

        await store.add_watch(watch)

        # Verify it exists
        exists = await store.get_watch(watch.id)
        assert exists is not None

        # Delete it
        deleted = await store.delete_watch(watch.id)
        assert deleted is True

        # Verify it's gone
        gone = await store.get_watch(watch.id)
        assert gone is None

    async def test_get_all_watches_with_filter(self, store):
        """Test getting watches with tag filter"""
        unique_tag = f"filter-test-{uuid.uuid4().hex[:8]}"
        watches = [
            WatchRecord(
                id=str(uuid.uuid4()),
                url=f"https://filter-{i}-{uuid.uuid4().hex[:8]}.example.com",
                tag=unique_tag
            )
            for i in range(3)
        ]

        try:
            for w in watches:
                await store.add_watch(w)

            # Get by tag
            results = await store.get_all_watches(tag=unique_tag)
            assert len(results) == 3

            # Get with limit
            limited = await store.get_all_watches(tag=unique_tag, limit=2)
            assert len(limited) == 2

        finally:
            for w in watches:
                await store.delete_watch(w.id)


@pytest.mark.asyncio
@pytestmark_integration
class TestAsyncSnapshotOperations:
    """Async integration tests for snapshot operations"""

    async def test_add_and_get_snapshot(self, store):
        """Test adding and retrieving snapshots"""
        watch = WatchRecord(
            id=str(uuid.uuid4()),
            url=f"https://snapshot-{uuid.uuid4().hex[:8]}.example.com"
        )

        try:
            await store.add_watch(watch)

            snapshot = SnapshotRecord(
                id=str(uuid.uuid4()),
                watch_id=watch.id,
                content_hash=PostgreSQLStore.compute_content_hash("Test content"),
                captured_at=datetime.utcnow(),
                content_text="Test content"
            )

            await store.add_snapshot(snapshot)

            snapshots = await store.get_snapshots(watch.id)
            assert len(snapshots) == 1
            assert snapshots[0].content_hash == snapshot.content_hash

        finally:
            await store.delete_watch(watch.id)

    async def test_get_latest_snapshot(self, store):
        """Test getting the most recent snapshot"""
        watch = WatchRecord(
            id=str(uuid.uuid4()),
            url=f"https://latest-{uuid.uuid4().hex[:8]}.example.com"
        )

        try:
            await store.add_watch(watch)

            # Add multiple snapshots with different timestamps
            for i in range(3):
                snapshot = SnapshotRecord(
                    id=str(uuid.uuid4()),
                    watch_id=watch.id,
                    content_hash=f"hash-{i}",
                    captured_at=datetime.utcnow() - timedelta(hours=2-i),
                    content_text=f"Content {i}"
                )
                await store.add_snapshot(snapshot)

            latest = await store.get_latest_snapshot(watch.id)
            assert latest is not None
            assert latest.content_hash == "hash-2"  # Most recent

        finally:
            await store.delete_watch(watch.id)

    async def test_snapshot_with_extracted_data(self, store):
        """Test snapshots with extracted price/availability"""
        watch = WatchRecord(
            id=str(uuid.uuid4()),
            url=f"https://extract-{uuid.uuid4().hex[:8]}.example.com"
        )

        try:
            await store.add_watch(watch)

            snapshot = SnapshotRecord(
                id=str(uuid.uuid4()),
                watch_id=watch.id,
                content_hash="abc123",
                captured_at=datetime.utcnow(),
                extracted_prices=[
                    {"price": 99.99, "currency": "USD"},
                    {"price": 149.99, "currency": "USD"}
                ],
                extracted_availability="in_stock"
            )

            await store.add_snapshot(snapshot)

            retrieved = await store.get_latest_snapshot(watch.id)
            assert retrieved.extracted_prices is not None
            assert len(retrieved.extracted_prices) == 2
            assert retrieved.extracted_availability == "in_stock"

        finally:
            await store.delete_watch(watch.id)

    async def test_delete_old_snapshots(self, store):
        """Test pruning old snapshots"""
        watch = WatchRecord(
            id=str(uuid.uuid4()),
            url=f"https://prune-{uuid.uuid4().hex[:8]}.example.com"
        )

        try:
            await store.add_watch(watch)

            # Add 5 snapshots
            for i in range(5):
                snapshot = SnapshotRecord(
                    id=str(uuid.uuid4()),
                    watch_id=watch.id,
                    content_hash=f"hash-{i}",
                    captured_at=datetime.utcnow() - timedelta(hours=4-i)
                )
                await store.add_snapshot(snapshot)

            # Keep only 2
            deleted = await store.delete_old_snapshots(watch.id, keep_count=2)
            assert deleted == 3

            remaining = await store.get_snapshots(watch.id)
            assert len(remaining) == 2

        finally:
            await store.delete_watch(watch.id)

    async def test_cascade_delete(self, store):
        """Test that snapshots are deleted when watch is deleted"""
        watch = WatchRecord(
            id=str(uuid.uuid4()),
            url=f"https://cascade-{uuid.uuid4().hex[:8]}.example.com"
        )

        await store.add_watch(watch)

        # Add a snapshot
        snapshot = SnapshotRecord(
            id=str(uuid.uuid4()),
            watch_id=watch.id,
            content_hash="test",
            captured_at=datetime.utcnow()
        )
        await store.add_snapshot(snapshot)

        # Delete watch (should cascade)
        await store.delete_watch(watch.id)

        # Snapshots should be gone
        snapshots = await store.get_snapshots(watch.id)
        assert len(snapshots) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
