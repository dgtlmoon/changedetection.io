"""
Comprehensive Tests for PostgreSQLStore

Tests all acceptance criteria for US-003:
- PostgreSQLStore class implementing ChangeDetectionStore interface
- add_watch() inserts into events table
- update_watch() updates events table
- delete() cascade deletes event and related history
- Connection pooling configured (10 connections)
- Graceful handling of database connection failures
- Data migration utility from JSON to PostgreSQL

Run with: pytest tasks/test_postgresql_store.py -v
"""

import json
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Configure pytest-anyio for async tests
pytestmark = pytest.mark.anyio

# Import the store and related classes
from tasks.postgresql_store import (
    POOL_MAX_SIZE,
    POOL_MIN_SIZE,
    JSONToPostgreSQLMigrator,
    PostgreSQLStore,
)
from tasks.models import SlackWebhookValidationError

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def database_url():
    """Get database URL from environment or use test default."""
    return os.getenv('DATABASE_URL', 'postgresql://test:test@localhost:5432/test_db')


@pytest.fixture
def temp_datastore(tmp_path):
    """Create a temporary datastore directory."""
    datastore = tmp_path / "datastore"
    datastore.mkdir()
    return str(datastore)


@pytest.fixture
def sample_json_data():
    """Sample JSON data for migration testing."""
    return {
        'watching': {
            'uuid-1': {
                'url': 'https://example.com/page1',
                'title': 'Test Watch 1',
                'paused': False,
                'tags': ['tag-uuid-1'],
                'fetch_backend': 'html_requests',
                'processor': 'text_json_diff',
                'include_filters': [],
                'headers': {},
                'notification_urls': [],
                'time_between_check': {'hours': 1},
                'date_created': 1700000000,
                'last_checked': 1700001000,
            },
            'uuid-2': {
                'url': 'https://example.com/page2',
                'title': 'Test Watch 2',
                'paused': True,
                'tags': ['tag-uuid-1', 'tag-uuid-2'],
                'fetch_backend': 'playwright',
                'processor': 'text_json_diff',
                'include_filters': ['.price', '#availability'],
                'headers': {'User-Agent': 'Test'},
                'notification_urls': ['http://webhook.test/notify'],
                'time_between_check': {'minutes': 30},
                'date_created': 1700000500,
            },
        },
        'settings': {
            'headers': {},
            'requests': {'time_between_check': {'hours': 3}, 'timeout': 15, 'proxy': None},
            'application': {
                'tags': {
                    'tag-uuid-1': {'title': 'Concerts', 'date_created': 1699999000},
                    'tag-uuid-2': {'title': 'Sports', 'date_created': 1699999500},
                },
                'notification_title': 'Test Notification',
                'notification_body': 'URL changed: {{ watch_url }}',
                'schema_version': 25,
            },
        },
        'version_tag': '0.46.0',
    }


# =============================================================================
# Unit Tests for PostgreSQLStore Initialization
# =============================================================================


class TestPostgreSQLStoreInit:
    """Test PostgreSQLStore initialization."""

    def test_init_with_database_url(self, database_url, temp_datastore):
        """Test initialization with explicit database URL."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)
        assert store.database_url == database_url
        assert store.datastore_path == temp_datastore
        assert store._initialized is False

    def test_init_from_environment(self, temp_datastore, monkeypatch):
        """Test initialization from DATABASE_URL environment variable."""
        test_url = 'postgresql://env:env@localhost/env_db'
        monkeypatch.setenv('DATABASE_URL', test_url)

        store = PostgreSQLStore(datastore_path=temp_datastore)
        assert store.database_url == test_url

    def test_init_without_url_raises_error(self, temp_datastore, monkeypatch):
        """Test that initialization without DATABASE_URL raises ValueError."""
        monkeypatch.delenv('DATABASE_URL', raising=False)

        with pytest.raises(ValueError, match="DATABASE_URL must be provided"):
            PostgreSQLStore(datastore_path=temp_datastore)

    def test_default_settings(self, database_url, temp_datastore):
        """Test that default settings are properly initialized."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)
        settings = store._settings_cache

        assert 'headers' in settings
        assert 'requests' in settings
        assert 'application' in settings
        assert settings['requests']['time_between_check']['hours'] == 3
        assert settings['application']['schema_version'] == 25


# =============================================================================
# Unit Tests for Connection Pooling
# =============================================================================


class TestConnectionPooling:
    """Test connection pool configuration."""

    def test_pool_size_constants(self):
        """Test that pool size constants are correct."""
        assert POOL_MIN_SIZE == 2
        assert POOL_MAX_SIZE == 10

    async def test_pool_not_initialized_error(self, database_url, temp_datastore):
        """Test that operations fail before initialization."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)

        with pytest.raises(RuntimeError, match="Store not initialized"):
            async with store.acquire():
                pass

        with pytest.raises(RuntimeError, match="Store not initialized"):
            async with store.session():
                pass


# =============================================================================
# Unit Tests for Watch CRUD Operations
# =============================================================================


class TestWatchCRUDOperations:
    """Test watch CRUD operations."""

    async def test_add_watch_basic(self, database_url, temp_datastore):
        """Test basic watch addition."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)

        # Mock both session and add_tag to avoid nested mocking issues
        with patch.object(store, 'session') as mock_session:
            mock_session_instance = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_session_instance.add = MagicMock()
            mock_session_instance.commit = AsyncMock()
            mock_session_instance.get = AsyncMock(return_value=None)

            store._initialized = True  # Bypass initialization check

            # Also mock add_tag to return a valid UUID
            with patch.object(store, 'add_tag', new_callable=AsyncMock) as mock_add_tag:
                mock_add_tag.return_value = str(uuid.uuid4())

                watch_uuid = await store.add_watch(
                    url='https://example.com/test',
                    tag='concerts',
                    extras={'title': 'Test Event', 'paused': False},
                )

                assert watch_uuid is not None
                assert len(watch_uuid) == 36  # UUID format

    async def test_add_watch_with_multiple_tags(self, database_url, temp_datastore):
        """Test watch addition with multiple comma-separated tags."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)

        with patch.object(store, 'session') as mock_session:
            mock_session_instance = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_session_instance.add = MagicMock()
            mock_session_instance.commit = AsyncMock()
            mock_session_instance.get = AsyncMock(return_value=None)
            mock_session_instance.execute = AsyncMock()
            mock_session_instance.execute.return_value.scalar_one_or_none = MagicMock(
                return_value=None
            )

            store._initialized = True

            watch_uuid = await store.add_watch(
                url='https://example.com/multi-tag', tag='concerts, sports, theater'
            )

            assert watch_uuid is not None

    async def test_url_exists_check(self, database_url, temp_datastore):
        """Test URL existence check."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)

        with patch.object(store, 'session') as mock_session:
            mock_session_instance = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            # Mock URL exists
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = MagicMock()  # URL exists
            mock_session_instance.execute = AsyncMock(return_value=mock_result)

            store._initialized = True

            exists = await store.url_exists('https://example.com/exists')
            assert exists is True

            # Mock URL doesn't exist
            mock_result.scalar_one_or_none.return_value = None
            exists = await store.url_exists('https://example.com/not-exists')
            assert exists is False


# =============================================================================
# Unit Tests for Update Operations
# =============================================================================


class TestUpdateOperations:
    """Test watch update operations."""

    async def test_update_watch_basic_fields(self, database_url, temp_datastore):
        """Test basic field updates."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)

        with patch.object(store, 'session') as mock_session:
            mock_session_instance = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_event = MagicMock()
            mock_event.extra_config = {}
            mock_session_instance.get = AsyncMock(return_value=mock_event)
            mock_session_instance.commit = AsyncMock()

            store._initialized = True

            test_uuid = str(uuid.uuid4())
            await store.update_watch(
                test_uuid, {'paused': True, 'title': 'Updated Title', 'check_interval': 7200}
            )

            assert mock_event.paused is True
            assert mock_event.event_name == 'Updated Title'
            assert mock_event.check_interval == 7200

    async def test_update_watch_time_between_check(self, database_url, temp_datastore):
        """Test time_between_check conversion to check_interval."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)

        with patch.object(store, 'session') as mock_session:
            mock_session_instance = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_event = MagicMock()
            mock_event.extra_config = {}
            mock_session_instance.get = AsyncMock(return_value=mock_event)
            mock_session_instance.commit = AsyncMock()

            store._initialized = True

            test_uuid = str(uuid.uuid4())
            await store.update_watch(test_uuid, {'time_between_check': {'hours': 2, 'minutes': 30}})

            # 2 hours + 30 minutes = 9000 seconds
            assert mock_event.check_interval == 9000

    async def test_update_watch_not_found(self, database_url, temp_datastore):
        """Test update when watch doesn't exist."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)

        with patch.object(store, 'session') as mock_session:
            mock_session_instance = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_session_instance.get = AsyncMock(return_value=None)

            store._initialized = True

            test_uuid = str(uuid.uuid4())
            # Should not raise, just log warning
            await store.update_watch(test_uuid, {'paused': True})


# =============================================================================
# Unit Tests for Delete Operations
# =============================================================================


class TestDeleteOperations:
    """Test watch delete operations."""

    async def test_delete_single_watch(self, database_url, temp_datastore):
        """Test deleting a single watch."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)

        with patch.object(store, 'session') as mock_session:
            mock_session_instance = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_event = MagicMock()
            mock_session_instance.get = AsyncMock(return_value=mock_event)
            mock_session_instance.delete = AsyncMock()
            mock_session_instance.commit = AsyncMock()

            store._initialized = True

            test_uuid = str(uuid.uuid4())
            await store.delete(test_uuid)

            mock_session_instance.delete.assert_called_once_with(mock_event)
            mock_session_instance.commit.assert_called_once()

    async def test_delete_all_watches(self, database_url, temp_datastore):
        """Test deleting all watches."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)

        with patch.object(store, 'session') as mock_session:
            mock_session_instance = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_session_instance.execute = AsyncMock()
            mock_session_instance.commit = AsyncMock()

            store._initialized = True

            await store.delete('all')

            mock_session_instance.execute.assert_called_once()
            mock_session_instance.commit.assert_called_once()

    async def test_delete_invalid_uuid(self, database_url, temp_datastore):
        """Test delete with invalid UUID."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)

        with patch.object(store, 'session') as mock_session:
            mock_session_instance = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            store._initialized = True

            # Should not raise, just log error
            await store.delete('not-a-valid-uuid')


# =============================================================================
# Unit Tests for History Clear
# =============================================================================


class TestHistoryClear:
    """Test watch history clearing (cascade delete of related records)."""

    async def test_clear_watch_history(self, database_url, temp_datastore):
        """Test clearing all history for a watch."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)

        with patch.object(store, 'session') as mock_session:
            mock_session_instance = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_session_instance.execute = AsyncMock()
            mock_session_instance.commit = AsyncMock()

            store._initialized = True

            test_uuid = str(uuid.uuid4())
            await store.clear_watch_history(test_uuid)

            # Should have executed deletes for PriceHistory, AvailabilityHistory, and Snapshot
            assert mock_session_instance.execute.call_count == 3
            mock_session_instance.commit.assert_called_once()


# =============================================================================
# Unit Tests for Tag Operations
# =============================================================================


class TestTagOperations:
    """Test tag operations."""

    async def test_add_new_tag(self, database_url, temp_datastore):
        """Test adding a new tag."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)

        with patch.object(store, 'session') as mock_session:
            mock_session_instance = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            # Mock tag doesn't exist
            with patch('tasks.postgresql_store.Tag') as MockTag:
                MockTag.get_by_name = AsyncMock(return_value=None)

                mock_tag = MagicMock()
                mock_tag.id = uuid.uuid4()
                MockTag.return_value = mock_tag

                mock_session_instance.add = MagicMock()
                mock_session_instance.commit = AsyncMock()

                store._initialized = True

                tag_uuid = await store.add_tag('Concerts')
                assert tag_uuid is not None

    async def test_add_existing_tag_returns_existing(self, database_url, temp_datastore):
        """Test that adding existing tag returns existing UUID."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)

        with patch.object(store, 'session') as mock_session:
            mock_session_instance = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            existing_uuid = uuid.uuid4()
            with patch('tasks.postgresql_store.Tag') as MockTag:
                mock_existing = MagicMock()
                mock_existing.id = existing_uuid
                MockTag.get_by_name = AsyncMock(return_value=mock_existing)

                store._initialized = True

                tag_uuid = await store.add_tag('Existing Tag')
                assert tag_uuid == str(existing_uuid)

    async def test_add_empty_tag_returns_none(self, database_url, temp_datastore):
        """Test that adding empty tag returns None."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)

        store._initialized = True

        tag_uuid = await store.add_tag('')
        assert tag_uuid is None

        tag_uuid = await store.add_tag('   ')
        assert tag_uuid is None


# =============================================================================
# Unit Tests for Search Operations
# =============================================================================


class TestSearchOperations:
    """Test search operations."""

    async def test_search_watches_partial_match(self, database_url, temp_datastore):
        """Test search with partial matching."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)

        with patch.object(store, 'session') as mock_session:
            mock_session_instance = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_event1 = MagicMock()
            mock_event1.id = uuid.uuid4()
            mock_event2 = MagicMock()
            mock_event2.id = uuid.uuid4()

            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [mock_event1, mock_event2]
            mock_session_instance.execute = AsyncMock(return_value=mock_result)

            store._initialized = True

            results = await store.search_watches_for_url('example', partial=True)
            assert len(results) == 2

    async def test_search_watches_exact_match(self, database_url, temp_datastore):
        """Test search with exact matching."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)

        with patch.object(store, 'session') as mock_session:
            mock_session_instance = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_session_instance.execute = AsyncMock(return_value=mock_result)

            store._initialized = True

            results = await store.search_watches_for_url('https://exact.com', partial=False)
            assert len(results) == 0


# =============================================================================
# Unit Tests for Data Conversion
# =============================================================================


class TestDataConversion:
    """Test data format conversion methods."""

    def test_event_to_watch_dict_conversion(self, database_url, temp_datastore):
        """Test converting Event model to watch dict format."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)

        mock_event = MagicMock()
        mock_event.id = uuid.uuid4()
        mock_event.url = 'https://example.com'
        mock_event.event_name = 'Test Event'
        mock_event.paused = False
        mock_event.check_interval = 3600
        mock_event.last_checked = datetime(2024, 1, 1, tzinfo=timezone.utc)
        mock_event.last_changed = datetime(2024, 1, 2, tzinfo=timezone.utc)
        mock_event.created_at = datetime(2023, 12, 1, tzinfo=timezone.utc)
        mock_event.include_filters = ['.price']
        mock_event.headers = {'User-Agent': 'Test'}
        mock_event.fetch_backend = 'html_requests'
        mock_event.processor = 'text_json_diff'
        mock_event.notification_urls = []
        mock_event.tags = []
        mock_event.extra_config = {'viewed': True}

        watch_dict = store._event_to_watch_dict(mock_event)

        assert watch_dict['uuid'] == str(mock_event.id)
        assert watch_dict['url'] == 'https://example.com'
        assert watch_dict['title'] == 'Test Event'
        assert watch_dict['paused'] is False
        assert watch_dict['check_interval'] == 3600
        assert watch_dict['include_filters'] == ['.price']
        assert watch_dict['fetch_backend'] == 'html_requests'


# =============================================================================
# Unit Tests for Migration Utility
# =============================================================================


class TestJSONToPostgreSQLMigrator:
    """Test JSON to PostgreSQL migration utility."""

    async def test_migrate_tags(self, tmp_path, database_url, sample_json_data):
        """Test migrating tags from JSON to PostgreSQL."""
        json_path = tmp_path / "url-watches.json"
        with open(json_path, 'w') as f:
            json.dump(sample_json_data, f)

        migrator = JSONToPostgreSQLMigrator(json_path=str(json_path), database_url=database_url)

        # Mock the store methods
        with patch.object(migrator.store, 'initialize', new_callable=AsyncMock):
            with patch.object(migrator.store, 'close', new_callable=AsyncMock):
                with patch.object(
                    migrator.store, 'add_tag', new_callable=AsyncMock
                ) as mock_add_tag:
                    mock_add_tag.side_effect = ['new-tag-uuid-1', 'new-tag-uuid-2']

                    with patch.object(
                        migrator.store, 'add_watch', new_callable=AsyncMock
                    ) as mock_add_watch:
                        mock_add_watch.return_value = 'new-watch-uuid'

                        stats = await migrator.migrate()

                        assert stats['tags_migrated'] == 2
                        assert stats['watches_migrated'] == 2
                        assert len(stats['errors']) == 0

    async def test_migrate_handles_invalid_json(self, tmp_path, database_url):
        """Test migration handles invalid JSON gracefully."""
        json_path = tmp_path / "invalid.json"
        with open(json_path, 'w') as f:
            f.write("not valid json")

        migrator = JSONToPostgreSQLMigrator(json_path=str(json_path), database_url=database_url)

        stats = await migrator.migrate()

        assert len(stats['errors']) > 0
        assert 'Failed to load JSON' in stats['errors'][0]


# =============================================================================
# Unit Tests for Proxy Operations
# =============================================================================


class TestProxyOperations:
    """Test proxy list and preferred proxy operations."""

    def test_proxy_list_from_file(self, database_url, temp_datastore):
        """Test loading proxy list from file."""
        # Create proxies.json
        proxies = {
            'proxy1': {'label': 'Proxy 1', 'url': 'http://proxy1.com:8080'},
            'proxy2': {'label': 'Proxy 2', 'url': 'http://proxy2.com:8080'},
        }
        proxies_file = os.path.join(temp_datastore, 'proxies.json')
        with open(proxies_file, 'w') as f:
            json.dump(proxies, f)

        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)

        proxy_list = store.proxy_list
        assert proxy_list is not None
        assert 'proxy1' in proxy_list
        assert 'proxy2' in proxy_list
        assert 'no-proxy' in proxy_list  # Always added

    def test_proxy_list_empty_without_file(self, database_url, temp_datastore):
        """Test proxy list is None when no proxies configured."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)

        # No proxies.json file
        proxy_list = store.proxy_list
        assert proxy_list is None


# =============================================================================
# Unit Tests for Properties
# =============================================================================


class TestStoreProperties:
    """Test store property methods."""

    def test_threshold_seconds_calculation(self, database_url, temp_datastore):
        """Test threshold seconds calculation from settings."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)

        # Default is 3 hours
        assert store.threshold_seconds == 3 * 3600

        # Modify settings
        store._settings_cache['requests']['time_between_check'] = {
            'days': 1,
            'hours': 2,
            'minutes': 30,
        }

        expected = 1 * 86400 + 2 * 3600 + 30 * 60
        assert store.threshold_seconds == expected

    def test_data_property(self, database_url, temp_datastore):
        """Test data property returns expected structure."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)

        data = store.data
        assert 'watching' in data
        assert 'settings' in data
        assert 'version_tag' in data


# =============================================================================
# Unit Tests for Error Handling
# =============================================================================


class TestErrorHandling:
    """Test graceful error handling."""

    async def test_handles_invalid_uuid_gracefully(self, database_url, temp_datastore):
        """Test that invalid UUIDs are handled gracefully."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)

        with patch.object(store, 'session') as mock_session:
            mock_session_instance = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            store._initialized = True

            # These should not raise exceptions
            await store.update_watch('invalid-uuid', {'paused': True})
            await store.delete('invalid-uuid')

            result = await store.get_watch('invalid-uuid')
            assert result is None

            tags = await store.get_all_tags_for_watch('invalid-uuid')
            assert tags == {}


# =============================================================================
# Integration-like Tests (with Mocked Database)
# =============================================================================


class TestIntegrationScenarios:
    """Test complete workflow scenarios."""

    async def test_full_watch_lifecycle(self, database_url, temp_datastore):
        """Test complete watch lifecycle: add, update, search, delete."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)

        with patch.object(store, 'session') as mock_session:
            mock_session_instance = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_event = MagicMock()
            mock_event.id = uuid.uuid4()
            mock_event.url = 'https://lifecycle-test.com'
            mock_event.event_name = 'Lifecycle Test'
            mock_event.paused = False
            mock_event.extra_config = {}
            mock_event.tags = []

            mock_session_instance.add = MagicMock()
            mock_session_instance.commit = AsyncMock()
            mock_session_instance.get = AsyncMock(return_value=mock_event)
            mock_session_instance.delete = AsyncMock()

            store._initialized = True

            # Also mock add_tag to return a valid UUID
            with patch.object(store, 'add_tag', new_callable=AsyncMock) as mock_add_tag:
                mock_add_tag.return_value = str(uuid.uuid4())

                # Add watch
                watch_uuid = await store.add_watch(url='https://lifecycle-test.com', tag='test')
                assert watch_uuid is not None

            # Update watch
            await store.update_watch(watch_uuid, {'paused': True})
            assert mock_event.paused is True

            # Delete watch
            await store.delete(watch_uuid)
            mock_session_instance.delete.assert_called()


# =============================================================================
# Tag Webhook Operations Tests (US-004)
# =============================================================================


class TestTagWebhookOperations:
    """Test tag webhook CRUD operations."""

    async def test_update_tag_with_valid_webhook(self, database_url, temp_datastore):
        """Test updating a tag with a valid webhook URL."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)

        with patch.object(store, 'session') as mock_session:
            mock_session_instance = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            # Mock the Tag.update_tag class method
            mock_tag = MagicMock()
            mock_tag.id = uuid.uuid4()
            mock_tag.name = 'test_tag'
            mock_tag.slack_webhook_url = 'https://hooks.slack.com/services/T12345678/B12345678/abc123'
            mock_tag.notification_muted = False
            mock_tag.color = '#3B82F6'
            mock_tag.created_at = datetime.now(timezone.utc)

            store._initialized = True

            with patch('tasks.models.Tag.update_tag', new_callable=AsyncMock) as mock_update:
                mock_update.return_value = mock_tag

                result = await store.update_tag(
                    tag_uuid=str(mock_tag.id),
                    slack_webhook_url='https://hooks.slack.com/services/T12345678/B12345678/abc123',
                    notification_muted=False,
                )

                assert result is not None
                assert result['slack_webhook_url'] == mock_tag.slack_webhook_url
                assert result['notification_muted'] is False

    async def test_update_tag_invalid_uuid(self, database_url, temp_datastore):
        """Test that updating with an invalid UUID returns None."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)

        with patch.object(store, 'session') as mock_session:
            mock_session_instance = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            store._initialized = True

            result = await store.update_tag(
                tag_uuid='not-a-valid-uuid',
                slack_webhook_url='https://hooks.slack.com/services/T12345678/B12345678/abc123',
            )

            assert result is None

    async def test_update_tag_with_invalid_webhook_raises_error(
        self, database_url, temp_datastore
    ):
        """Test that updating with an invalid webhook URL raises an error."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)

        with patch.object(store, 'session') as mock_session:
            mock_session_instance = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            store._initialized = True

            with patch(
                'tasks.models.Tag.update_tag', new_callable=AsyncMock
            ) as mock_update:
                mock_update.side_effect = SlackWebhookValidationError(
                    "Invalid Slack webhook URL format"
                )

                with pytest.raises(SlackWebhookValidationError):
                    await store.update_tag(
                        tag_uuid=str(uuid.uuid4()),
                        slack_webhook_url='https://example.com/invalid',
                    )

    async def test_get_webhooks_for_event(self, database_url, temp_datastore):
        """Test getting webhooks for an event."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)

        with patch.object(store, 'session') as mock_session:
            mock_session_instance = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            store._initialized = True

            expected_webhooks = [
                {
                    'tag_id': str(uuid.uuid4()),
                    'tag_name': 'concerts',
                    'webhook_url': 'https://hooks.slack.com/services/T11111111/B11111111/abc111',
                },
                {
                    'tag_id': str(uuid.uuid4()),
                    'tag_name': 'vip',
                    'webhook_url': 'https://hooks.slack.com/services/T22222222/B22222222/abc222',
                },
            ]

            with patch(
                'tasks.models.Tag.get_webhooks_for_event', new_callable=AsyncMock
            ) as mock_get:
                mock_get.return_value = expected_webhooks

                event_uuid = str(uuid.uuid4())
                webhooks = await store.get_webhooks_for_event(event_uuid)

                assert len(webhooks) == 2
                assert webhooks[0]['webhook_url'] == expected_webhooks[0]['webhook_url']
                assert webhooks[1]['tag_name'] == 'vip'

    async def test_get_webhooks_for_event_invalid_uuid(self, database_url, temp_datastore):
        """Test that invalid event UUID returns empty list."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)

        with patch.object(store, 'session') as mock_session:
            mock_session_instance = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            store._initialized = True

            webhooks = await store.get_webhooks_for_event('not-a-valid-uuid')
            assert webhooks == []

    async def test_get_tag(self, database_url, temp_datastore):
        """Test getting a tag by UUID."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)

        with patch.object(store, 'session') as mock_session:
            mock_session_instance = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_tag = MagicMock()
            mock_tag.id = uuid.uuid4()
            mock_tag.name = 'concerts'
            mock_tag.slack_webhook_url = 'https://hooks.slack.com/services/T12345678/B12345678/abc123'
            mock_tag.notification_muted = False
            mock_tag.color = '#EF4444'
            mock_tag.created_at = datetime.now(timezone.utc)

            store._initialized = True

            with patch('tasks.models.Tag.get_by_id', new_callable=AsyncMock) as mock_get:
                mock_get.return_value = mock_tag

                result = await store.get_tag(str(mock_tag.id))

                assert result is not None
                assert result['title'] == 'concerts'
                assert result['slack_webhook_url'] == mock_tag.slack_webhook_url

    async def test_get_all_tags(self, database_url, temp_datastore):
        """Test getting all tags."""
        store = PostgreSQLStore(database_url=database_url, datastore_path=temp_datastore)

        with patch.object(store, 'session') as mock_session:
            mock_session_instance = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_tags = []
            for i, name in enumerate(['concerts', 'sports', 'comedy']):
                tag = MagicMock()
                tag.id = uuid.uuid4()
                tag.name = name
                tag.slack_webhook_url = f'https://hooks.slack.com/services/T{i:08d}/B{i:08d}/abc{i:03d}'
                tag.notification_muted = False
                tag.color = '#3B82F6'
                tag.created_at = datetime.now(timezone.utc)
                mock_tags.append(tag)

            store._initialized = True

            with patch('tasks.models.Tag.get_all', new_callable=AsyncMock) as mock_get:
                mock_get.return_value = mock_tags

                result = await store.get_all_tags()

                assert len(result) == 3
                assert result[0]['title'] == 'concerts'
                assert result[1]['title'] == 'sports'
                assert result[2]['title'] == 'comedy'


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
