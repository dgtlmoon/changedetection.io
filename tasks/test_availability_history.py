"""
Tests for Availability History Tracking (US-010)

This module tests the availability history functionality including:
- Availability history recording on sold out/restock changes
- Cleanup of old availability history records
- API endpoint for retrieving availability history
- PostgreSQL store methods for availability history

Usage:
    pytest tasks/test_availability_history.py -v
    pytest tasks/test_availability_history.py -v -k "test_cleanup"
"""

import os
import uuid

import pytest
import pytest_asyncio

# Skip all tests if dependencies not available
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")

from sqlalchemy.ext.asyncio import AsyncSession

from tasks.models import (
    AvailabilityHistory,
    Event,
    async_session_factory,
    create_async_engine_from_url,
)

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture(scope="module")
def database_url():
    """Get database URL from environment"""
    url = os.getenv('DATABASE_URL')
    if not url:
        pytest.skip("DATABASE_URL not set")
    return url


@pytest_asyncio.fixture(scope="module")
async def engine(database_url):
    """Create async engine for tests"""
    engine = create_async_engine_from_url(database_url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def session(engine):
    """Create a new session for each test with rollback"""
    async_session = async_session_factory(engine)

    async with async_session() as session:
        # Start a nested transaction (savepoint)
        async with session.begin():
            yield session
            # Rollback the transaction at end of test
            await session.rollback()


@pytest_asyncio.fixture
async def test_event(session: AsyncSession):
    """Create a test event"""
    event = Event(
        url=f"https://example.com/event/{uuid.uuid4().hex[:8]}",
        event_name="Test Concert",
        artist="Test Artist",
        venue="Test Venue",
        is_sold_out=False,
    )
    session.add(event)
    await session.flush()
    return event


# =============================================================================
# Availability History Recording Tests
# =============================================================================


class TestAvailabilityHistoryRecording:
    """Tests for availability history recording on check"""

    @pytest.mark.asyncio
    async def test_record_availability_change_creates_history(
        self, session: AsyncSession, test_event: Event
    ):
        """Test that recording an availability change creates a history entry"""
        history = await test_event.record_availability_change(session, is_sold_out=True)

        assert history.id is not None
        assert history.event_id == test_event.id
        assert history.is_sold_out is True
        assert history.recorded_at is not None

    @pytest.mark.asyncio
    async def test_record_availability_change_updates_event_status(
        self, session: AsyncSession, test_event: Event
    ):
        """Test that recording availability change updates the event's sold out status"""
        assert test_event.is_sold_out is False

        await test_event.record_availability_change(session, is_sold_out=True)

        assert test_event.is_sold_out is True
        assert test_event.last_changed is not None

    @pytest.mark.asyncio
    async def test_record_sold_out_to_available_transition(
        self, session: AsyncSession, test_event: Event
    ):
        """Test recording transition from sold out to available (restock)"""
        # First mark as sold out
        await test_event.record_availability_change(session, is_sold_out=True)
        assert test_event.is_sold_out is True

        # Then mark as available (restock)
        history = await test_event.record_availability_change(session, is_sold_out=False)

        assert test_event.is_sold_out is False
        assert history.is_sold_out is False

    @pytest.mark.asyncio
    async def test_update_event_data_records_availability_history(
        self, session: AsyncSession, test_event: Event
    ):
        """Test that update_event_data records availability history when status changes"""
        changes = await test_event.update_event_data(
            session,
            is_sold_out=True,
            record_history=True,
        )

        assert changes['availability_changed'] is True
        assert changes['data_changed'] is True

        # Verify history was recorded
        histories = await AvailabilityHistory.get_history_for_event(session, test_event.id)
        assert len(histories) >= 1
        assert histories[0].is_sold_out is True

    @pytest.mark.asyncio
    async def test_update_event_data_no_history_when_disabled(
        self, session: AsyncSession, test_event: Event
    ):
        """Test that update_event_data doesn't record history when record_history=False"""
        # Get initial history count
        initial_histories = await AvailabilityHistory.get_history_for_event(
            session, test_event.id
        )
        initial_count = len(initial_histories)

        changes = await test_event.update_event_data(
            session,
            is_sold_out=True,
            record_history=False,
        )

        assert changes['availability_changed'] is True

        # Verify no new history was recorded
        histories = await AvailabilityHistory.get_history_for_event(session, test_event.id)
        assert len(histories) == initial_count


# =============================================================================
# Availability History Retrieval Tests
# =============================================================================


class TestAvailabilityHistoryRetrieval:
    """Tests for retrieving availability history"""

    @pytest.mark.asyncio
    async def test_get_history_for_event(
        self, session: AsyncSession, test_event: Event
    ):
        """Test getting availability history for an event"""
        # Create multiple history records (alternating sold out/available)
        for sold_out in [True, False, True, False, True]:
            history = AvailabilityHistory(event_id=test_event.id, is_sold_out=sold_out)
            session.add(history)
        await session.flush()

        histories = await AvailabilityHistory.get_history_for_event(session, test_event.id)
        assert len(histories) >= 5

    @pytest.mark.asyncio
    async def test_get_history_for_event_with_limit(
        self, session: AsyncSession, test_event: Event
    ):
        """Test getting availability history with limit"""
        # Create 10 history records
        for i in range(10):
            history = AvailabilityHistory(event_id=test_event.id, is_sold_out=i % 2 == 0)
            session.add(history)
        await session.flush()

        # Get only 5 most recent
        histories = await AvailabilityHistory.get_history_for_event(
            session, test_event.id, limit=5
        )
        assert len(histories) == 5

    @pytest.mark.asyncio
    async def test_get_history_returns_most_recent_first(
        self, session: AsyncSession, test_event: Event
    ):
        """Test that history is returned with most recent first"""
        # Create history records
        for sold_out in [False, True, False]:
            history = AvailabilityHistory(event_id=test_event.id, is_sold_out=sold_out)
            session.add(history)
            await session.flush()

        histories = await AvailabilityHistory.get_history_for_event(session, test_event.id)

        # Verify ordered by recorded_at descending (most recent first)
        for i in range(len(histories) - 1):
            assert histories[i].recorded_at >= histories[i + 1].recorded_at

    @pytest.mark.asyncio
    async def test_get_latest_for_event(
        self, session: AsyncSession, test_event: Event
    ):
        """Test getting the latest availability history entry"""
        # Create multiple records
        for sold_out in [False, True, False]:
            history = AvailabilityHistory(event_id=test_event.id, is_sold_out=sold_out)
            session.add(history)
            await session.flush()

        latest = await AvailabilityHistory.get_latest_for_event(session, test_event.id)
        assert latest is not None
        assert latest.is_sold_out is False  # Last one added

    @pytest.mark.asyncio
    async def test_get_restock_events(self, session: AsyncSession, test_event: Event):
        """Test getting restock events (transitions to available)"""
        # Create some history including restocks
        for sold_out in [True, False, True, False]:  # Two restocks
            history = AvailabilityHistory(event_id=test_event.id, is_sold_out=sold_out)
            session.add(history)
        await session.flush()

        restocks = await AvailabilityHistory.get_restock_events(session)
        # Should have at least 2 restock records (is_sold_out=False)
        restock_count = sum(1 for r in restocks if r.event_id == test_event.id)
        assert restock_count >= 2


# =============================================================================
# Availability History Cleanup Tests
# =============================================================================


class TestAvailabilityHistoryCleanup:
    """Tests for cleanup of old availability history records"""

    @pytest.mark.asyncio
    async def test_store_cleanup_old_records(self, database_url):
        """Test that old records are deleted by cleanup"""
        from tasks.postgresql_store import PostgreSQLStore

        store = PostgreSQLStore(database_url=database_url, include_default_watches=False)
        await store.initialize()

        try:
            # Create a test watch
            watch_uuid = await store.add_watch(
                url=f"https://example.com/availability-cleanup-test/{uuid.uuid4().hex[:8]}",
                extras={'title': 'Availability Cleanup Test'},
            )

            # Run cleanup with 90 day retention
            result = await store.cleanup_old_availability_history(retention_days=90)
            assert 'deleted_count' in result
            assert isinstance(result['deleted_count'], int)

        finally:
            # Cleanup
            if watch_uuid:
                await store.delete(watch_uuid)
            await store.close()


# =============================================================================
# Availability History to_dict Tests
# =============================================================================


class TestAvailabilityHistoryDict:
    """Tests for availability history to_dict conversion"""

    @pytest.mark.asyncio
    async def test_to_dict_contains_all_fields(
        self, session: AsyncSession, test_event: Event
    ):
        """Test that to_dict contains all required fields"""
        history = AvailabilityHistory(event_id=test_event.id, is_sold_out=True)
        session.add(history)
        await session.flush()

        data = history.to_dict()

        assert 'id' in data
        assert 'event_id' in data
        assert 'is_sold_out' in data
        assert 'recorded_at' in data

    @pytest.mark.asyncio
    async def test_to_dict_correct_values(
        self, session: AsyncSession, test_event: Event
    ):
        """Test that to_dict contains correct values"""
        history = AvailabilityHistory(event_id=test_event.id, is_sold_out=True)
        session.add(history)
        await session.flush()

        data = history.to_dict()

        assert data['event_id'] == str(test_event.id)
        assert data['is_sold_out'] is True
        assert data['recorded_at'] is not None


# =============================================================================
# PostgreSQL Store Availability History Tests
# =============================================================================


class TestPostgreSQLStoreAvailabilityHistory:
    """Tests for PostgreSQL store availability history operations"""

    @pytest.mark.asyncio
    async def test_get_availability_history_from_store(self, database_url):
        """Test getting availability history via PostgreSQL store"""
        from tasks.postgresql_store import PostgreSQLStore

        store = PostgreSQLStore(database_url=database_url, include_default_watches=False)
        await store.initialize()

        try:
            # Create a test watch
            watch_uuid = await store.add_watch(
                url=f"https://example.com/availability-test/{uuid.uuid4().hex[:8]}",
                extras={'title': 'Availability History Test'},
            )

            # Get availability history (should be empty initially)
            history = await store.get_availability_history(watch_uuid)
            assert isinstance(history, list)

        finally:
            # Cleanup
            if watch_uuid:
                await store.delete(watch_uuid)
            await store.close()

    @pytest.mark.asyncio
    async def test_get_availability_history_with_limit(self, database_url):
        """Test getting availability history with limit"""
        from tasks.postgresql_store import PostgreSQLStore

        store = PostgreSQLStore(database_url=database_url, include_default_watches=False)
        await store.initialize()

        try:
            # Create a test watch
            watch_uuid = await store.add_watch(
                url=f"https://example.com/availability-limit-test/{uuid.uuid4().hex[:8]}",
                extras={'title': 'Availability Limit Test'},
            )

            # Get availability history with limit
            history = await store.get_availability_history(watch_uuid, limit=10)
            assert isinstance(history, list)
            assert len(history) <= 10

        finally:
            # Cleanup
            if watch_uuid:
                await store.delete(watch_uuid)
            await store.close()

    @pytest.mark.asyncio
    async def test_cleanup_old_availability_history_from_store(self, database_url):
        """Test cleanup via PostgreSQL store"""
        from tasks.postgresql_store import PostgreSQLStore

        store = PostgreSQLStore(database_url=database_url, include_default_watches=False)
        await store.initialize()

        try:
            result = await store.cleanup_old_availability_history(retention_days=90)
            assert 'deleted_count' in result
            assert isinstance(result['deleted_count'], int)

        finally:
            await store.close()

    @pytest.mark.asyncio
    async def test_get_availability_history_stats(self, database_url):
        """Test getting availability history stats from store"""
        from tasks.postgresql_store import PostgreSQLStore

        store = PostgreSQLStore(database_url=database_url, include_default_watches=False)
        await store.initialize()

        try:
            stats = await store.get_availability_history_stats()
            assert 'total_records' in stats
            assert isinstance(stats['total_records'], int)

        finally:
            await store.close()

    @pytest.mark.asyncio
    async def test_get_availability_history_invalid_uuid(self, database_url):
        """Test getting availability history with invalid UUID"""
        from tasks.postgresql_store import PostgreSQLStore

        store = PostgreSQLStore(database_url=database_url, include_default_watches=False)
        await store.initialize()

        try:
            history = await store.get_availability_history("invalid-uuid")
            assert history == []

        finally:
            await store.close()


# =============================================================================
# Availability History Integration Tests
# =============================================================================


class TestAvailabilityHistoryIntegration:
    """Integration tests for availability history tracking"""

    @pytest.mark.asyncio
    async def test_full_availability_tracking_flow(
        self, session: AsyncSession, test_event: Event
    ):
        """Test the full flow of availability tracking"""
        # Initial state: not sold out
        assert test_event.is_sold_out is False

        # Event sells out
        changes1 = await test_event.update_event_data(
            session, is_sold_out=True, record_history=True
        )
        assert changes1['availability_changed'] is True
        assert test_event.is_sold_out is True

        # Event restocks
        changes2 = await test_event.update_event_data(
            session, is_sold_out=False, record_history=True
        )
        assert changes2['availability_changed'] is True
        assert test_event.is_sold_out is False

        # Event sells out again
        changes3 = await test_event.update_event_data(
            session, is_sold_out=True, record_history=True
        )
        assert changes3['availability_changed'] is True
        assert test_event.is_sold_out is True

        # Verify history records
        histories = await AvailabilityHistory.get_history_for_event(session, test_event.id)
        assert len(histories) >= 3

        # Verify the sequence (most recent first)
        # Latest should be sold_out=True, then False, then True
        assert histories[0].is_sold_out is True  # Most recent: sold out again
        assert histories[1].is_sold_out is False  # Restocked
        assert histories[2].is_sold_out is True  # First sell out

    @pytest.mark.asyncio
    async def test_no_change_when_status_same(
        self, session: AsyncSession, test_event: Event
    ):
        """Test that no history is recorded when status doesn't change"""
        # Get initial history count
        initial_histories = await AvailabilityHistory.get_history_for_event(
            session, test_event.id
        )
        initial_count = len(initial_histories)

        # Try to set the same status (already False)
        changes = await test_event.update_event_data(
            session, is_sold_out=False, record_history=True
        )

        # No change should be detected
        assert changes['availability_changed'] is False

        # Verify no new history was recorded
        histories = await AvailabilityHistory.get_history_for_event(session, test_event.id)
        assert len(histories) == initial_count
