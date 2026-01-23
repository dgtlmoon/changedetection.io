"""
Tests for PostgreSQL Schema V2

This test suite verifies that:
1. All tables are created correctly with proper constraints
2. Indexes are created for performance
3. Foreign key relationships work correctly
4. Sample data can be inserted and queried
5. Cascading deletes work as expected

Usage:
    # Run with pytest (requires DATABASE_URL environment variable)
    pytest tasks/test_schema_v2.py -v

    # Run specific test
    pytest tasks/test_schema_v2.py::TestSchemaCreation -v
"""

import os
import uuid
import pytest
from datetime import datetime, date, time
from decimal import Decimal

# Mark for integration tests that require DATABASE_URL
requires_database = pytest.mark.skipif(
    not os.getenv('DATABASE_URL'),
    reason="DATABASE_URL environment variable not set"
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
async def pool():
    """Create a connection pool for testing."""
    import asyncpg

    database_url = os.getenv('DATABASE_URL')
    pool = await asyncpg.create_pool(
        database_url,
        min_size=1,
        max_size=5,
        command_timeout=60
    )

    yield pool

    await pool.close()


@pytest.fixture
async def clean_pool(pool):
    """Provide a pool with clean tables (all data deleted)."""
    async with pool.acquire() as conn:
        # Delete in reverse dependency order
        await conn.execute("DELETE FROM notification_log")
        await conn.execute("DELETE FROM availability_history")
        await conn.execute("DELETE FROM price_history")
        await conn.execute("DELETE FROM snapshots")
        await conn.execute("DELETE FROM event_tags")
        await conn.execute("DELETE FROM events")
        await conn.execute("DELETE FROM tags")
        await conn.execute("DELETE FROM users")

    yield pool


# =============================================================================
# Schema Creation Tests (Integration - requires DATABASE_URL)
# =============================================================================

@requires_database
class TestSchemaCreation:
    """Test that schema is created correctly."""

    @pytest.mark.asyncio
    async def test_apply_schema_creates_all_tables(self, pool):
        """Verify all required tables exist."""
        from tasks.schema_v2 import apply_schema_v2

        await apply_schema_v2(pool)

        async with pool.acquire() as conn:
            tables = await conn.fetch("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name
            """)

            table_names = [t['table_name'] for t in tables]

            # Check all required tables exist
            expected_tables = [
                'users',
                'tags',
                'events',
                'event_tags',
                'price_history',
                'availability_history',
                'notification_log',
                'snapshots',
                'schema_version'
            ]

            for table in expected_tables:
                assert table in table_names, f"Table '{table}' not found"

    @pytest.mark.asyncio
    async def test_users_table_has_correct_columns(self, pool):
        """Verify users table has all required columns."""
        async with pool.acquire() as conn:
            columns = await conn.fetch("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = 'users'
                ORDER BY ordinal_position
            """)

            column_names = [c['column_name'] for c in columns]

            expected_columns = ['id', 'email', 'password_hash', 'role', 'created_at', 'last_login', 'is_active']
            for col in expected_columns:
                assert col in column_names, f"Column '{col}' not found in users table"

    @pytest.mark.asyncio
    async def test_tags_table_has_correct_columns(self, pool):
        """Verify tags table has all required columns."""
        async with pool.acquire() as conn:
            columns = await conn.fetch("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'tags'
            """)

            column_names = [c['column_name'] for c in columns]

            expected_columns = ['id', 'name', 'slack_webhook_url', 'notification_muted', 'color', 'created_at', 'created_by']
            for col in expected_columns:
                assert col in column_names, f"Column '{col}' not found in tags table"

    @pytest.mark.asyncio
    async def test_events_table_has_correct_columns(self, pool):
        """Verify events table has all required columns."""
        async with pool.acquire() as conn:
            columns = await conn.fetch("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'events'
            """)

            column_names = [c['column_name'] for c in columns]

            expected_columns = [
                'id', 'url', 'event_name', 'artist', 'venue', 'event_date', 'event_time',
                'current_price_low', 'current_price_high', 'is_sold_out', 'ticket_types',
                'track_specific_types', 'check_interval', 'paused', 'include_filters',
                'css_selectors', 'headers', 'fetch_backend', 'processor',
                'created_at', 'last_checked', 'last_changed', 'extra_config', 'notification_urls'
            ]
            for col in expected_columns:
                assert col in column_names, f"Column '{col}' not found in events table"

    @pytest.mark.asyncio
    async def test_price_history_table_has_correct_columns(self, pool):
        """Verify price_history table has all required columns."""
        async with pool.acquire() as conn:
            columns = await conn.fetch("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'price_history'
            """)

            column_names = [c['column_name'] for c in columns]

            expected_columns = ['id', 'event_id', 'price_low', 'price_high', 'ticket_type', 'recorded_at']
            for col in expected_columns:
                assert col in column_names, f"Column '{col}' not found in price_history table"

    @pytest.mark.asyncio
    async def test_indexes_are_created(self, pool):
        """Verify performance indexes are created."""
        async with pool.acquire() as conn:
            indexes = await conn.fetch("""
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public'
            """)

            index_names = [i['indexname'] for i in indexes]

            expected_indexes = [
                'idx_users_email',
                'idx_tags_name',
                'idx_events_url',
                'idx_events_event_date',
                'idx_price_history_event_id',
                'idx_availability_history_event_id',
                'idx_notification_log_event_id',
            ]

            for idx in expected_indexes:
                assert idx in index_names, f"Index '{idx}' not found"


# =============================================================================
# Data Insertion Tests (Integration - requires DATABASE_URL)
# =============================================================================

@requires_database
class TestDataInsertion:
    """Test data insertion operations."""

    @pytest.mark.asyncio
    async def test_insert_user(self, clean_pool):
        """Test inserting a user record."""
        async with clean_pool.acquire() as conn:
            user_id = str(uuid.uuid4())
            await conn.execute("""
                INSERT INTO users (id, email, password_hash, role)
                VALUES ($1, $2, $3, $4)
            """, user_id, 'test@example.com', 'hashedpassword', 'admin')

            row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
            assert row is not None
            assert row['email'] == 'test@example.com'
            assert row['role'] == 'admin'
            assert row['is_active'] is True

    @pytest.mark.asyncio
    async def test_insert_tag_with_webhook(self, clean_pool):
        """Test inserting a tag with Slack webhook."""
        async with clean_pool.acquire() as conn:
            tag_id = str(uuid.uuid4())
            webhook_url = 'https://hooks.slack.com/services/T00/B00/xxx'

            await conn.execute("""
                INSERT INTO tags (id, name, slack_webhook_url, color)
                VALUES ($1, $2, $3, $4)
            """, tag_id, 'concerts', webhook_url, '#FF0000')

            row = await conn.fetchrow("SELECT * FROM tags WHERE id = $1", tag_id)
            assert row is not None
            assert row['name'] == 'concerts'
            assert row['slack_webhook_url'] == webhook_url
            assert row['notification_muted'] is False

    @pytest.mark.asyncio
    async def test_insert_event_with_all_fields(self, clean_pool):
        """Test inserting an event with all fields populated."""
        async with clean_pool.acquire() as conn:
            event_id = str(uuid.uuid4())

            await conn.execute("""
                INSERT INTO events (
                    id, url, event_name, artist, venue, event_date, event_time,
                    current_price_low, current_price_high, is_sold_out,
                    check_interval, paused
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12
                )
            """,
                event_id,
                'https://metrochicago.com/event/test',
                'Test Concert',
                'Test Artist',
                'Metro Chicago',
                date(2026, 3, 15),
                time(20, 0),
                Decimal('35.00'),
                Decimal('75.00'),
                False,
                1800,
                False
            )

            row = await conn.fetchrow("SELECT * FROM events WHERE id = $1", event_id)
            assert row is not None
            assert row['event_name'] == 'Test Concert'
            assert row['artist'] == 'Test Artist'
            assert row['current_price_low'] == Decimal('35.00')

    @pytest.mark.asyncio
    async def test_insert_event_tag_relationship(self, clean_pool):
        """Test many-to-many relationship between events and tags."""
        async with clean_pool.acquire() as conn:
            # Create event
            event_id = str(uuid.uuid4())
            await conn.execute("""
                INSERT INTO events (id, url, event_name)
                VALUES ($1, $2, $3)
            """, event_id, 'https://example.com/event', 'Test Event')

            # Create tags
            tag_id_1 = str(uuid.uuid4())
            tag_id_2 = str(uuid.uuid4())
            await conn.execute("INSERT INTO tags (id, name) VALUES ($1, $2)", tag_id_1, 'tag1')
            await conn.execute("INSERT INTO tags (id, name) VALUES ($1, $2)", tag_id_2, 'tag2')

            # Link event to both tags
            await conn.execute("""
                INSERT INTO event_tags (event_id, tag_id) VALUES ($1, $2)
            """, event_id, tag_id_1)
            await conn.execute("""
                INSERT INTO event_tags (event_id, tag_id) VALUES ($1, $2)
            """, event_id, tag_id_2)

            # Query tags for event
            tags = await conn.fetch("""
                SELECT t.name FROM tags t
                JOIN event_tags et ON t.id = et.tag_id
                WHERE et.event_id = $1
            """, event_id)

            assert len(tags) == 2
            tag_names = [t['name'] for t in tags]
            assert 'tag1' in tag_names
            assert 'tag2' in tag_names

    @pytest.mark.asyncio
    async def test_insert_price_history(self, clean_pool):
        """Test inserting price history records."""
        async with clean_pool.acquire() as conn:
            # Create event first
            event_id = str(uuid.uuid4())
            await conn.execute("""
                INSERT INTO events (id, url) VALUES ($1, $2)
            """, event_id, 'https://example.com/event')

            # Insert price history
            for i, (low, high) in enumerate([(30, 70), (32, 72), (35, 75)]):
                await conn.execute("""
                    INSERT INTO price_history (event_id, price_low, price_high, ticket_type)
                    VALUES ($1, $2, $3, $4)
                """, event_id, Decimal(str(low)), Decimal(str(high)), 'GA')

            # Query history
            history = await conn.fetch("""
                SELECT * FROM price_history
                WHERE event_id = $1
                ORDER BY recorded_at DESC
            """, event_id)

            assert len(history) == 3
            assert history[0]['price_low'] == Decimal('35.00')

    @pytest.mark.asyncio
    async def test_insert_availability_history(self, clean_pool):
        """Test inserting availability history records."""
        async with clean_pool.acquire() as conn:
            # Create event first
            event_id = str(uuid.uuid4())
            await conn.execute("""
                INSERT INTO events (id, url) VALUES ($1, $2)
            """, event_id, 'https://example.com/event')

            # Insert availability changes
            for sold_out in [False, True, False]:
                await conn.execute("""
                    INSERT INTO availability_history (event_id, is_sold_out)
                    VALUES ($1, $2)
                """, event_id, sold_out)

            # Query history
            history = await conn.fetch("""
                SELECT * FROM availability_history
                WHERE event_id = $1
                ORDER BY recorded_at DESC
            """, event_id)

            assert len(history) == 3

    @pytest.mark.asyncio
    async def test_insert_notification_log(self, clean_pool):
        """Test inserting notification log records."""
        async with clean_pool.acquire() as conn:
            # Create event and tag first
            event_id = str(uuid.uuid4())
            tag_id = str(uuid.uuid4())
            await conn.execute("INSERT INTO events (id, url) VALUES ($1, $2)", event_id, 'https://example.com/event')
            await conn.execute("INSERT INTO tags (id, name) VALUES ($1, $2)", tag_id, 'test-tag')

            # Insert notification log
            import json
            await conn.execute("""
                INSERT INTO notification_log (
                    event_id, tag_id, notification_type, webhook_url,
                    payload, response_status, success
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
                event_id,
                tag_id,
                'restock',
                'https://hooks.slack.com/test',
                json.dumps({'text': 'RESTOCK ALERT'}),
                200,
                True
            )

            row = await conn.fetchrow("""
                SELECT * FROM notification_log WHERE event_id = $1
            """, event_id)

            assert row is not None
            assert row['notification_type'] == 'restock'
            assert row['success'] is True


# =============================================================================
# Constraint Tests (Integration - requires DATABASE_URL)
# =============================================================================

@requires_database
class TestConstraints:
    """Test database constraints."""

    @pytest.mark.asyncio
    async def test_user_email_unique(self, clean_pool):
        """Test that user email must be unique."""
        async with clean_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (email, password_hash, role)
                VALUES ('test@example.com', 'hash', 'admin')
            """)

            with pytest.raises(Exception) as exc_info:
                await conn.execute("""
                    INSERT INTO users (email, password_hash, role)
                    VALUES ('test@example.com', 'hash2', 'viewer')
                """)

            assert 'unique' in str(exc_info.value).lower() or 'duplicate' in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_user_role_check(self, clean_pool):
        """Test that user role must be admin or viewer."""
        async with clean_pool.acquire() as conn:
            with pytest.raises(Exception):
                await conn.execute("""
                    INSERT INTO users (email, password_hash, role)
                    VALUES ('test@example.com', 'hash', 'invalid_role')
                """)

    @pytest.mark.asyncio
    async def test_event_url_not_empty(self, clean_pool):
        """Test that event URL cannot be empty."""
        async with clean_pool.acquire() as conn:
            with pytest.raises(Exception):
                await conn.execute("""
                    INSERT INTO events (url) VALUES ('')
                """)

    @pytest.mark.asyncio
    async def test_notification_type_check(self, clean_pool):
        """Test that notification type must be valid."""
        async with clean_pool.acquire() as conn:
            with pytest.raises(Exception):
                await conn.execute("""
                    INSERT INTO notification_log (notification_type)
                    VALUES ('invalid_type')
                """)


# =============================================================================
# Cascade Delete Tests (Integration - requires DATABASE_URL)
# =============================================================================

@requires_database
class TestCascadeDeletes:
    """Test cascade delete behavior."""

    @pytest.mark.asyncio
    async def test_delete_event_cascades_to_price_history(self, clean_pool):
        """Test that deleting an event deletes its price history."""
        async with clean_pool.acquire() as conn:
            event_id = str(uuid.uuid4())
            await conn.execute("INSERT INTO events (id, url) VALUES ($1, $2)", event_id, 'https://example.com')
            await conn.execute("INSERT INTO price_history (event_id, price_low) VALUES ($1, $2)", event_id, Decimal('50'))

            # Verify price history exists
            count = await conn.fetchval("SELECT COUNT(*) FROM price_history WHERE event_id = $1", event_id)
            assert count == 1

            # Delete event
            await conn.execute("DELETE FROM events WHERE id = $1", event_id)

            # Verify price history is deleted
            count = await conn.fetchval("SELECT COUNT(*) FROM price_history WHERE event_id = $1", event_id)
            assert count == 0

    @pytest.mark.asyncio
    async def test_delete_event_cascades_to_event_tags(self, clean_pool):
        """Test that deleting an event removes tag associations."""
        async with clean_pool.acquire() as conn:
            event_id = str(uuid.uuid4())
            tag_id = str(uuid.uuid4())

            await conn.execute("INSERT INTO events (id, url) VALUES ($1, $2)", event_id, 'https://example.com')
            await conn.execute("INSERT INTO tags (id, name) VALUES ($1, $2)", tag_id, 'test')
            await conn.execute("INSERT INTO event_tags (event_id, tag_id) VALUES ($1, $2)", event_id, tag_id)

            # Delete event
            await conn.execute("DELETE FROM events WHERE id = $1", event_id)

            # Verify event_tags is deleted but tag remains
            count = await conn.fetchval("SELECT COUNT(*) FROM event_tags WHERE event_id = $1", event_id)
            assert count == 0

            tag = await conn.fetchrow("SELECT * FROM tags WHERE id = $1", tag_id)
            assert tag is not None

    @pytest.mark.asyncio
    async def test_delete_tag_cascades_to_event_tags(self, clean_pool):
        """Test that deleting a tag removes event associations."""
        async with clean_pool.acquire() as conn:
            event_id = str(uuid.uuid4())
            tag_id = str(uuid.uuid4())

            await conn.execute("INSERT INTO events (id, url) VALUES ($1, $2)", event_id, 'https://example.com')
            await conn.execute("INSERT INTO tags (id, name) VALUES ($1, $2)", tag_id, 'test')
            await conn.execute("INSERT INTO event_tags (event_id, tag_id) VALUES ($1, $2)", event_id, tag_id)

            # Delete tag
            await conn.execute("DELETE FROM tags WHERE id = $1", tag_id)

            # Verify event_tags is deleted but event remains
            count = await conn.fetchval("SELECT COUNT(*) FROM event_tags WHERE tag_id = $1", tag_id)
            assert count == 0

            event = await conn.fetchrow("SELECT * FROM events WHERE id = $1", event_id)
            assert event is not None


# =============================================================================
# Sample Data Tests (Integration - requires DATABASE_URL)
# =============================================================================

@requires_database
class TestSampleData:
    """Test sample data insertion."""

    @pytest.mark.asyncio
    async def test_insert_sample_data(self, pool):
        """Test that sample data can be inserted."""
        from tasks.schema_v2 import apply_schema_v2, insert_sample_data

        await apply_schema_v2(pool)
        await insert_sample_data(pool)

        async with pool.acquire() as conn:
            # Verify sample users exist
            user_count = await conn.fetchval("SELECT COUNT(*) FROM users")
            assert user_count >= 2

            # Verify sample tags exist
            tag_count = await conn.fetchval("SELECT COUNT(*) FROM tags")
            assert tag_count >= 3

            # Verify sample event exists
            event_count = await conn.fetchval("SELECT COUNT(*) FROM events")
            assert event_count >= 1

            # Verify price history exists
            price_count = await conn.fetchval("SELECT COUNT(*) FROM price_history")
            assert price_count >= 3


# =============================================================================
# Data Model Tests (Unit Tests - No Database)
# =============================================================================

class TestDataModels:
    """Test data model classes without database."""

    def test_user_record_to_dict(self):
        """Test UserRecord serialization."""
        from tasks.schema_v2 import UserRecord

        user = UserRecord(
            id='test-id',
            email='test@example.com',
            password_hash='hash',
            role='admin',
            created_at=datetime(2026, 1, 15, 10, 30, 0)
        )

        result = user.to_dict()
        assert result['id'] == 'test-id'
        assert result['email'] == 'test@example.com'
        assert result['created_at'] == '2026-01-15T10:30:00'

    def test_event_record_to_dict(self):
        """Test EventRecord serialization."""
        from tasks.schema_v2 import EventRecord

        event = EventRecord(
            id='test-id',
            url='https://example.com/event',
            event_name='Test Event',
            current_price_low=35.0,
            current_price_high=75.0
        )

        result = event.to_dict()
        assert result['url'] == 'https://example.com/event'
        assert result['current_price_low'] == 35.0

    def test_price_history_record_to_dict(self):
        """Test PriceHistoryRecord serialization."""
        from tasks.schema_v2 import PriceHistoryRecord

        record = PriceHistoryRecord(
            id='test-id',
            event_id='event-id',
            price_low=30.0,
            price_high=70.0,
            ticket_type='GA',
            recorded_at=datetime(2026, 1, 15, 10, 30, 0)
        )

        result = record.to_dict()
        assert result['ticket_type'] == 'GA'
        assert result['recorded_at'] == '2026-01-15T10:30:00'


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
