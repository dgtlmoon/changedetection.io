"""
Tests for Price History Tracking (US-009)

This module tests the price history functionality including:
- Price history recording on check
- Cleanup of old price history records
- API endpoint for retrieving price history
- Background job for price history cleanup

Usage:
    pytest tasks/test_price_history.py -v
    pytest tasks/test_price_history.py -v -k "test_cleanup"
"""

import os
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio

# Skip all tests if dependencies not available
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")

from sqlalchemy.ext.asyncio import AsyncSession

from tasks.models import (
    Event,
    PriceHistory,
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
        current_price_low=Decimal("25.00"),
        current_price_high=Decimal("75.00"),
        is_sold_out=False,
    )
    session.add(event)
    await session.flush()
    return event


# =============================================================================
# Price History Recording Tests
# =============================================================================


class TestPriceHistoryRecording:
    """Tests for price history recording on check"""

    @pytest.mark.asyncio
    async def test_record_price_change_creates_history(
        self, session: AsyncSession, test_event: Event
    ):
        """Test that recording a price change creates a history entry"""
        history = await test_event.record_price_change(
            session,
            price_low=Decimal("30.00"),
            price_high=Decimal("80.00"),
            ticket_type="GA",
        )

        assert history.id is not None
        assert history.event_id == test_event.id
        assert history.price_low == Decimal("30.00")
        assert history.price_high == Decimal("80.00")
        assert history.ticket_type == "GA"
        assert history.recorded_at is not None

    @pytest.mark.asyncio
    async def test_record_price_change_updates_current_price(
        self, session: AsyncSession, test_event: Event
    ):
        """Test that recording a price change updates the event's current price"""
        original_low = test_event.current_price_low
        original_high = test_event.current_price_high

        await test_event.record_price_change(
            session,
            price_low=Decimal("35.00"),
            price_high=Decimal("85.00"),
        )

        assert test_event.current_price_low == Decimal("35.00")
        assert test_event.current_price_high == Decimal("85.00")
        assert test_event.current_price_low != original_low
        assert test_event.current_price_high != original_high

    @pytest.mark.asyncio
    async def test_update_event_data_records_price_history(
        self, session: AsyncSession, test_event: Event
    ):
        """Test that update_event_data records price history when prices change"""
        changes = await test_event.update_event_data(
            session,
            current_price_low=Decimal("40.00"),
            current_price_high=Decimal("90.00"),
            record_history=True,
        )

        assert changes['price_changed'] is True
        assert changes['data_changed'] is True

        # Verify history was recorded
        histories = await PriceHistory.get_history_for_event(session, test_event.id)
        assert len(histories) >= 1
        assert histories[0].price_low == Decimal("40.00")
        assert histories[0].price_high == Decimal("90.00")

    @pytest.mark.asyncio
    async def test_update_event_data_no_history_when_disabled(
        self, session: AsyncSession, test_event: Event
    ):
        """Test that update_event_data doesn't record history when record_history=False"""
        # Get initial history count
        initial_histories = await PriceHistory.get_history_for_event(session, test_event.id)
        initial_count = len(initial_histories)

        changes = await test_event.update_event_data(
            session,
            current_price_low=Decimal("45.00"),
            current_price_high=Decimal("95.00"),
            record_history=False,
        )

        assert changes['price_changed'] is True

        # Verify no new history was recorded
        histories = await PriceHistory.get_history_for_event(session, test_event.id)
        assert len(histories) == initial_count

    @pytest.mark.asyncio
    async def test_price_history_includes_ticket_type(
        self, session: AsyncSession, test_event: Event
    ):
        """Test that price history can include ticket type for specific type tracking"""
        history = await test_event.record_price_change(
            session,
            price_low=Decimal("50.00"),
            price_high=Decimal("100.00"),
            ticket_type="VIP",
        )

        assert history.ticket_type == "VIP"

        # Retrieve and verify
        retrieved = await PriceHistory.get_latest_for_event(session, test_event.id)
        assert retrieved.ticket_type == "VIP"


# =============================================================================
# Price History Retrieval Tests
# =============================================================================


class TestPriceHistoryRetrieval:
    """Tests for retrieving price history"""

    @pytest.mark.asyncio
    async def test_get_history_for_event(
        self, session: AsyncSession, test_event: Event
    ):
        """Test getting price history for an event"""
        # Create multiple history records
        for i in range(5):
            history = PriceHistory(
                event_id=test_event.id,
                price_low=Decimal(f"{20 + i * 5}.00"),
                price_high=Decimal(f"{70 + i * 5}.00"),
            )
            session.add(history)
        await session.flush()

        histories = await PriceHistory.get_history_for_event(session, test_event.id)
        assert len(histories) >= 5

    @pytest.mark.asyncio
    async def test_get_history_for_event_with_limit(
        self, session: AsyncSession, test_event: Event
    ):
        """Test getting price history with limit"""
        # Create 10 history records
        for i in range(10):
            history = PriceHistory(
                event_id=test_event.id,
                price_low=Decimal(f"{20 + i}.00"),
                price_high=Decimal(f"{70 + i}.00"),
            )
            session.add(history)
        await session.flush()

        # Get only 5 most recent
        histories = await PriceHistory.get_history_for_event(
            session, test_event.id, limit=5
        )
        assert len(histories) == 5

    @pytest.mark.asyncio
    async def test_get_history_returns_most_recent_first(
        self, session: AsyncSession, test_event: Event
    ):
        """Test that history is returned with most recent first"""
        # Create history records
        for i in range(3):
            history = PriceHistory(
                event_id=test_event.id,
                price_low=Decimal(f"{20 + i * 10}.00"),
                price_high=Decimal(f"{70 + i * 10}.00"),
            )
            session.add(history)
            await session.flush()

        histories = await PriceHistory.get_history_for_event(session, test_event.id)

        # Verify ordered by recorded_at descending (most recent first)
        for i in range(len(histories) - 1):
            assert histories[i].recorded_at >= histories[i + 1].recorded_at

    @pytest.mark.asyncio
    async def test_get_latest_for_event(
        self, session: AsyncSession, test_event: Event
    ):
        """Test getting the latest price history entry"""
        # Create multiple records
        for i in range(3):
            history = PriceHistory(
                event_id=test_event.id,
                price_low=Decimal(f"{30 + i * 10}.00"),
                price_high=Decimal(f"{80 + i * 10}.00"),
            )
            session.add(history)
            await session.flush()

        latest = await PriceHistory.get_latest_for_event(session, test_event.id)
        assert latest is not None
        assert latest.price_low == Decimal("50.00")  # Last one added

    @pytest.mark.asyncio
    async def test_get_history_count(self, session: AsyncSession, test_event: Event):
        """Test getting total count of price history records"""
        # Create some records
        for i in range(3):
            history = PriceHistory(
                event_id=test_event.id,
                price_low=Decimal(f"{30 + i}.00"),
                price_high=Decimal(f"{80 + i}.00"),
            )
            session.add(history)
        await session.flush()

        count = await PriceHistory.get_history_count(session)
        assert count >= 3


# =============================================================================
# Price History Cleanup Tests
# =============================================================================


class TestPriceHistoryCleanup:
    """Tests for cleanup of old price history records"""

    @pytest.mark.asyncio
    async def test_cleanup_old_records(self, session: AsyncSession, test_event: Event):
        """Test that old records are deleted by cleanup"""
        from datetime import timezone

        from sqlalchemy import update

        # Create old records (older than 90 days)
        old_date = datetime.now(timezone.utc) - timedelta(days=100)

        for i in range(5):
            history = PriceHistory(
                event_id=test_event.id,
                price_low=Decimal(f"{20 + i}.00"),
                price_high=Decimal(f"{70 + i}.00"),
            )
            session.add(history)
        await session.flush()

        # Manually set recorded_at to old date for testing
        await session.execute(
            update(PriceHistory)
            .where(PriceHistory.event_id == test_event.id)
            .values(recorded_at=old_date)
        )
        await session.commit()

        # Run cleanup with 90 day retention
        deleted_count = await PriceHistory.cleanup_old_records(session, retention_days=90)

        assert deleted_count >= 5

    @pytest.mark.asyncio
    async def test_cleanup_preserves_recent_records(
        self, session: AsyncSession, test_event: Event
    ):
        """Test that recent records are preserved by cleanup"""
        # Create recent records
        for i in range(3):
            history = PriceHistory(
                event_id=test_event.id,
                price_low=Decimal(f"{30 + i}.00"),
                price_high=Decimal(f"{80 + i}.00"),
            )
            session.add(history)
        await session.flush()

        # Get count before cleanup
        histories_before = await PriceHistory.get_history_for_event(session, test_event.id)
        count_before = len(histories_before)

        # Run cleanup - should not delete recent records
        await PriceHistory.cleanup_old_records(session, retention_days=90)

        # Verify records still exist
        histories_after = await PriceHistory.get_history_for_event(session, test_event.id)
        count_after = len(histories_after)

        assert count_after == count_before

    @pytest.mark.asyncio
    async def test_cleanup_configurable_retention(
        self, session: AsyncSession, test_event: Event
    ):
        """Test that retention period is configurable"""
        from datetime import timezone

        from sqlalchemy import update

        # Create records
        for i in range(3):
            history = PriceHistory(
                event_id=test_event.id,
                price_low=Decimal(f"{25 + i}.00"),
                price_high=Decimal(f"{75 + i}.00"),
            )
            session.add(history)
        await session.flush()

        # Set recorded_at to 35 days ago
        old_date = datetime.now(timezone.utc) - timedelta(days=35)
        await session.execute(
            update(PriceHistory)
            .where(PriceHistory.event_id == test_event.id)
            .values(recorded_at=old_date)
        )
        await session.commit()

        # Cleanup with 30 day retention should delete them
        deleted_count = await PriceHistory.cleanup_old_records(session, retention_days=30)
        assert deleted_count >= 3


# =============================================================================
# Price History to_dict Tests
# =============================================================================


class TestPriceHistoryDict:
    """Tests for price history to_dict conversion"""

    @pytest.mark.asyncio
    async def test_to_dict_contains_all_fields(
        self, session: AsyncSession, test_event: Event
    ):
        """Test that to_dict contains all required fields"""
        history = PriceHistory(
            event_id=test_event.id,
            price_low=Decimal("35.00"),
            price_high=Decimal("85.00"),
            ticket_type="VIP",
        )
        session.add(history)
        await session.flush()

        data = history.to_dict()

        assert 'id' in data
        assert 'event_id' in data
        assert 'price_low' in data
        assert 'price_high' in data
        assert 'ticket_type' in data
        assert 'recorded_at' in data

    @pytest.mark.asyncio
    async def test_to_dict_correct_values(
        self, session: AsyncSession, test_event: Event
    ):
        """Test that to_dict contains correct values"""
        history = PriceHistory(
            event_id=test_event.id,
            price_low=Decimal("40.00"),
            price_high=Decimal("90.00"),
            ticket_type="GA",
        )
        session.add(history)
        await session.flush()

        data = history.to_dict()

        assert data['event_id'] == str(test_event.id)
        assert data['price_low'] == 40.0
        assert data['price_high'] == 90.0
        assert data['ticket_type'] == "GA"

    @pytest.mark.asyncio
    async def test_to_dict_handles_none_values(
        self, session: AsyncSession, test_event: Event
    ):
        """Test that to_dict handles None values correctly"""
        history = PriceHistory(
            event_id=test_event.id,
            price_low=None,
            price_high=None,
            ticket_type=None,
        )
        session.add(history)
        await session.flush()

        data = history.to_dict()

        assert data['price_low'] is None
        assert data['price_high'] is None
        assert data['ticket_type'] is None


# =============================================================================
# PostgreSQL Store Price History Tests
# =============================================================================


class TestPostgreSQLStorePriceHistory:
    """Tests for PostgreSQL store price history operations"""

    @pytest.mark.asyncio
    async def test_get_price_history_from_store(self, database_url):
        """Test getting price history via PostgreSQL store"""
        from tasks.postgresql_store import PostgreSQLStore

        store = PostgreSQLStore(database_url=database_url, include_default_watches=False)
        await store.initialize()

        try:
            # Create a test watch
            watch_uuid = await store.add_watch(
                url=f"https://example.com/price-test/{uuid.uuid4().hex[:8]}",
                extras={'title': 'Price History Test'},
            )

            # Get price history (should be empty initially)
            history = await store.get_price_history(watch_uuid)
            assert isinstance(history, list)

        finally:
            # Cleanup
            if watch_uuid:
                await store.delete(watch_uuid)
            await store.close()

    @pytest.mark.asyncio
    async def test_cleanup_old_price_history_from_store(self, database_url):
        """Test cleanup via PostgreSQL store"""
        from tasks.postgresql_store import PostgreSQLStore

        store = PostgreSQLStore(database_url=database_url, include_default_watches=False)
        await store.initialize()

        try:
            result = await store.cleanup_old_price_history(retention_days=90)
            assert 'deleted_count' in result
            assert isinstance(result['deleted_count'], int)

        finally:
            await store.close()

    @pytest.mark.asyncio
    async def test_get_price_history_stats(self, database_url):
        """Test getting price history stats from store"""
        from tasks.postgresql_store import PostgreSQLStore

        store = PostgreSQLStore(database_url=database_url, include_default_watches=False)
        await store.initialize()

        try:
            stats = await store.get_price_history_stats()
            assert 'total_records' in stats
            assert isinstance(stats['total_records'], int)

        finally:
            await store.close()


# =============================================================================
# Price History Cleanup Job Tests
# =============================================================================


class TestPriceHistoryCleanupJob:
    """Tests for price history cleanup background job"""

    @pytest.mark.asyncio
    async def test_run_cleanup_job(self, database_url):
        """Test running the cleanup job"""
        from tasks.price_history_cleanup import run_price_history_cleanup

        result = await run_price_history_cleanup(
            database_url=database_url,
            retention_days=90,
        )

        assert result['success'] is True
        assert 'deleted_count' in result
        assert result['retention_days'] == 90

    def test_run_cleanup_job_sync(self, database_url):
        """Test running the cleanup job synchronously"""
        from tasks.price_history_cleanup import run_price_history_cleanup_sync

        result = run_price_history_cleanup_sync(
            database_url=database_url,
            retention_days=90,
        )

        assert result['success'] is True
        assert 'deleted_count' in result

    def test_run_cleanup_job_without_database_url(self):
        """Test that cleanup fails gracefully without DATABASE_URL"""
        import os

        from tasks.price_history_cleanup import run_price_history_cleanup_sync

        # Temporarily unset DATABASE_URL
        original = os.environ.pop('DATABASE_URL', None)
        try:
            result = run_price_history_cleanup_sync(database_url=None)
            assert result['success'] is False
            assert 'DATABASE_URL not provided' in result['error']
        finally:
            if original:
                os.environ['DATABASE_URL'] = original
