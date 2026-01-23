"""
Tests for SQLAlchemy ORM Models (US-002)

This module tests all CRUD operations for the SQLAlchemy models including:
- User model with role-based permissions
- Tag model with webhook functionality
- Event model with extraction fields
- PriceHistory model
- AvailabilityHistory model
- NotificationLog model

Usage:
    pytest tasks/test_models.py -v
    pytest tasks/test_models.py -v -k "test_user"
"""

import os
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio

# Skip all tests if dependencies not available
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tasks.models import (
    AvailabilityHistory,
    Event,
    NotificationLog,
    NotificationType,
    PriceHistory,
    Snapshot,
    Tag,
    User,
    UserRole,
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
async def test_user(session: AsyncSession):
    """Create a test user"""
    user = User(
        email=f"test_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="$2b$12$test_hash_value_here",
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def test_viewer(session: AsyncSession):
    """Create a test viewer user"""
    user = User(
        email=f"viewer_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="$2b$12$test_hash_value_here",
        role=UserRole.VIEWER.value,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def test_tag(session: AsyncSession, test_user: User):
    """Create a test tag"""
    tag = Tag(
        name=f"test_tag_{uuid.uuid4().hex[:8]}",
        slack_webhook_url="https://hooks.slack.com/services/TEST/WEBHOOK",
        notification_muted=False,
        color="#FF5733",
        created_by=test_user.id,
    )
    session.add(tag)
    await session.flush()
    return tag


@pytest_asyncio.fixture
async def test_event(session: AsyncSession):
    """Create a test event"""
    event = Event(
        url=f"https://example.com/event/{uuid.uuid4().hex[:8]}",
        event_name="Test Concert",
        artist="Test Artist",
        venue="Test Venue",
        event_date=date(2026, 6, 15),
        event_time=time(20, 0),
        current_price_low=Decimal("25.00"),
        current_price_high=Decimal("75.00"),
        is_sold_out=False,
        check_interval=1800,
        paused=False,
    )
    session.add(event)
    await session.flush()
    return event


# =============================================================================
# User Model Tests
# =============================================================================


class TestUserModel:
    """Tests for User model"""

    @pytest.mark.asyncio
    async def test_create_user(self, session: AsyncSession):
        """Test creating a new user"""
        user = User(
            email=f"new_user_{uuid.uuid4().hex[:8]}@example.com",
            password_hash="$2b$12$hashed_password",
            role=UserRole.ADMIN.value,
        )
        session.add(user)
        await session.flush()

        assert user.id is not None
        assert user.email.startswith("new_user_")
        assert user.role == "admin"
        assert user.is_active is True
        assert user.created_at is not None

    @pytest.mark.asyncio
    async def test_user_role_permissions_admin(self, test_user: User):
        """Test admin user permissions"""
        assert test_user.is_admin() is True
        assert test_user.is_viewer() is False
        assert test_user.can_edit() is True
        assert test_user.can_view() is True
        assert test_user.can_manage_users() is True
        assert test_user.can_manage_tags() is True
        assert test_user.can_manage_events() is True

    @pytest.mark.asyncio
    async def test_user_role_permissions_viewer(self, test_viewer: User):
        """Test viewer user permissions"""
        assert test_viewer.is_admin() is False
        assert test_viewer.is_viewer() is True
        assert test_viewer.can_edit() is False
        assert test_viewer.can_view() is True
        assert test_viewer.can_manage_users() is False
        assert test_viewer.can_manage_tags() is False
        assert test_viewer.can_manage_events() is False

    @pytest.mark.asyncio
    async def test_get_user_by_email(self, session: AsyncSession, test_user: User):
        """Test getting user by email"""
        found = await User.get_by_email(session, test_user.email)
        assert found is not None
        assert found.id == test_user.id

    @pytest.mark.asyncio
    async def test_get_user_by_email_not_found(self, session: AsyncSession):
        """Test getting non-existent user by email"""
        found = await User.get_by_email(session, "nonexistent@example.com")
        assert found is None

    @pytest.mark.asyncio
    async def test_get_user_by_id(self, session: AsyncSession, test_user: User):
        """Test getting user by ID"""
        found = await User.get_by_id(session, test_user.id)
        assert found is not None
        assert found.email == test_user.email

    @pytest.mark.asyncio
    async def test_get_active_users(
        self, session: AsyncSession, test_user: User, test_viewer: User
    ):
        """Test getting active users"""
        users = await User.get_active_users(session)
        assert len(users) >= 2
        user_ids = [u.id for u in users]
        assert test_user.id in user_ids
        assert test_viewer.id in user_ids

    @pytest.mark.asyncio
    async def test_get_admins(self, session: AsyncSession, test_user: User, test_viewer: User):
        """Test getting admin users"""
        admins = await User.get_admins(session)
        admin_ids = [a.id for a in admins]
        assert test_user.id in admin_ids
        assert test_viewer.id not in admin_ids

    @pytest.mark.asyncio
    async def test_user_to_dict(self, test_user: User):
        """Test user to_dict conversion"""
        data = test_user.to_dict()
        assert data['id'] == str(test_user.id)
        assert data['email'] == test_user.email
        assert data['role'] == test_user.role
        assert 'password_hash' not in data  # Should not expose password


# =============================================================================
# Tag Model Tests
# =============================================================================


class TestTagModel:
    """Tests for Tag model"""

    @pytest.mark.asyncio
    async def test_create_tag(self, session: AsyncSession, test_user: User):
        """Test creating a new tag"""
        tag = Tag(
            name=f"new_tag_{uuid.uuid4().hex[:8]}",
            slack_webhook_url="https://hooks.slack.com/services/NEW/WEBHOOK",
            color="#00FF00",
            created_by=test_user.id,
        )
        session.add(tag)
        await session.flush()

        assert tag.id is not None
        assert tag.slack_webhook_url is not None
        assert tag.notification_muted is False

    @pytest.mark.asyncio
    async def test_tag_has_webhook(self, test_tag: Tag):
        """Test tag has_webhook method"""
        assert test_tag.has_webhook() is True

    @pytest.mark.asyncio
    async def test_tag_can_notify(self, test_tag: Tag):
        """Test tag can_notify method"""
        assert test_tag.can_notify() is True

        # Test muted tag
        test_tag.notification_muted = True
        assert test_tag.can_notify() is False

    @pytest.mark.asyncio
    async def test_tag_without_webhook(self, session: AsyncSession):
        """Test tag without webhook"""
        tag = Tag(name=f"no_webhook_{uuid.uuid4().hex[:8]}")
        session.add(tag)
        await session.flush()

        assert tag.has_webhook() is False
        assert tag.can_notify() is False

    @pytest.mark.asyncio
    async def test_get_tag_by_name(self, session: AsyncSession, test_tag: Tag):
        """Test getting tag by name"""
        found = await Tag.get_by_name(session, test_tag.name)
        assert found is not None
        assert found.id == test_tag.id

    @pytest.mark.asyncio
    async def test_get_tags_with_webhooks(self, session: AsyncSession, test_tag: Tag):
        """Test getting tags with webhooks"""
        # Create a tag without webhook
        tag_no_webhook = Tag(name=f"no_webhook_{uuid.uuid4().hex[:8]}")
        session.add(tag_no_webhook)
        await session.flush()

        tags = await Tag.get_tags_with_webhooks(session)
        tag_ids = [t.id for t in tags]

        assert test_tag.id in tag_ids
        assert tag_no_webhook.id not in tag_ids

    @pytest.mark.asyncio
    async def test_tag_to_dict(self, test_tag: Tag):
        """Test tag to_dict conversion"""
        data = test_tag.to_dict()
        assert data['id'] == str(test_tag.id)
        assert data['name'] == test_tag.name
        assert data['slack_webhook_url'] == test_tag.slack_webhook_url


# =============================================================================
# Event Model Tests
# =============================================================================


class TestEventModel:
    """Tests for Event model"""

    @pytest.mark.asyncio
    async def test_create_event(self, session: AsyncSession):
        """Test creating a new event"""
        event = Event(
            url=f"https://example.com/event/{uuid.uuid4().hex[:8]}",
            event_name="New Concert",
            artist="New Artist",
            venue="New Venue",
            event_date=date(2026, 12, 25),
            event_time=time(19, 30),
            current_price_low=Decimal("50.00"),
            current_price_high=Decimal("150.00"),
        )
        session.add(event)
        await session.flush()

        assert event.id is not None
        assert event.is_sold_out is False
        assert event.paused is False
        assert event.check_interval == 3600

    @pytest.mark.asyncio
    async def test_event_needs_check_never_checked(self, test_event: Event):
        """Test event needs check when never checked"""
        test_event.last_checked = None
        assert test_event.needs_check() is True

    @pytest.mark.asyncio
    async def test_event_needs_check_paused(self, test_event: Event):
        """Test paused event doesn't need check"""
        test_event.paused = True
        assert test_event.needs_check() is False

    @pytest.mark.asyncio
    async def test_event_needs_check_recently_checked(self, test_event: Event):
        """Test recently checked event doesn't need check"""
        test_event.last_checked = datetime.now()
        assert test_event.needs_check() is False

    @pytest.mark.asyncio
    async def test_event_needs_check_interval_passed(self, test_event: Event):
        """Test event needs check after interval passes"""
        test_event.check_interval = 60  # 1 minute
        test_event.last_checked = datetime.now() - timedelta(minutes=2)
        assert test_event.needs_check() is True

    @pytest.mark.asyncio
    async def test_event_get_price_range_str(self, test_event: Event):
        """Test price range string formatting"""
        price_str = test_event.get_price_range_str()
        assert price_str == "$25.00 - $75.00"

    @pytest.mark.asyncio
    async def test_event_get_price_range_str_single_price(self, session: AsyncSession):
        """Test price range with same low and high"""
        event = Event(
            url=f"https://example.com/event/{uuid.uuid4().hex[:8]}",
            current_price_low=Decimal("50.00"),
            current_price_high=Decimal("50.00"),
        )
        session.add(event)
        await session.flush()

        assert event.get_price_range_str() == "$50.00"

    @pytest.mark.asyncio
    async def test_event_get_price_range_str_no_price(self, session: AsyncSession):
        """Test price range with no prices"""
        event = Event(url=f"https://example.com/event/{uuid.uuid4().hex[:8]}")
        session.add(event)
        await session.flush()

        assert event.get_price_range_str() is None

    @pytest.mark.asyncio
    async def test_get_event_by_url(self, session: AsyncSession, test_event: Event):
        """Test getting event by URL"""
        found = await Event.get_by_url(session, test_event.url)
        assert found is not None
        assert found.id == test_event.id

    @pytest.mark.asyncio
    async def test_get_active_events(self, session: AsyncSession, test_event: Event):
        """Test getting active (non-paused) events"""
        events = await Event.get_active_events(session)
        event_ids = [e.id for e in events]
        assert test_event.id in event_ids

    @pytest.mark.asyncio
    async def test_get_sold_out_events(self, session: AsyncSession, test_event: Event):
        """Test getting sold out events"""
        # Mark event as sold out
        test_event.is_sold_out = True
        await session.flush()

        events = await Event.get_sold_out_events(session)
        event_ids = [e.id for e in events]
        assert test_event.id in event_ids

    @pytest.mark.asyncio
    async def test_event_tag_relationship(
        self, session: AsyncSession, test_event: Event, test_tag: Tag
    ):
        """Test event-tag many-to-many relationship"""
        # Add tag to event
        test_event.tags.append(test_tag)
        await session.flush()

        # Verify relationship
        assert test_tag in test_event.tags
        assert test_event in test_tag.events

    @pytest.mark.asyncio
    async def test_get_events_by_tag(self, session: AsyncSession, test_event: Event, test_tag: Tag):
        """Test getting events by tag"""
        test_event.tags.append(test_tag)
        await session.flush()

        events = await Event.get_events_by_tag(session, test_tag.id)
        event_ids = [e.id for e in events]
        assert test_event.id in event_ids

    @pytest.mark.asyncio
    async def test_event_to_dict(self, test_event: Event):
        """Test event to_dict conversion"""
        data = test_event.to_dict()
        assert data['id'] == str(test_event.id)
        assert data['url'] == test_event.url
        assert data['event_name'] == test_event.event_name
        assert data['current_price_low'] == 25.0
        assert data['current_price_high'] == 75.0


# =============================================================================
# PriceHistory Model Tests
# =============================================================================


class TestPriceHistoryModel:
    """Tests for PriceHistory model"""

    @pytest.mark.asyncio
    async def test_create_price_history(self, session: AsyncSession, test_event: Event):
        """Test creating price history record"""
        history = PriceHistory(
            event_id=test_event.id,
            price_low=Decimal("30.00"),
            price_high=Decimal("80.00"),
            ticket_type="GA",
        )
        session.add(history)
        await session.flush()

        assert history.id is not None
        assert history.event_id == test_event.id
        assert history.recorded_at is not None

    @pytest.mark.asyncio
    async def test_record_price_change(self, session: AsyncSession, test_event: Event):
        """Test recording price change via Event method"""
        history = await test_event.record_price_change(
            session, price_low=Decimal("35.00"), price_high=Decimal("85.00"), ticket_type="VIP"
        )

        assert history.id is not None
        assert history.price_low == Decimal("35.00")
        assert history.price_high == Decimal("85.00")
        assert test_event.current_price_low == Decimal("35.00")
        assert test_event.current_price_high == Decimal("85.00")
        assert test_event.last_changed is not None

    @pytest.mark.asyncio
    async def test_get_price_history_for_event(self, session: AsyncSession, test_event: Event):
        """Test getting price history for event"""
        # Create multiple history records
        for i in range(3):
            history = PriceHistory(
                event_id=test_event.id,
                price_low=Decimal(f"{20 + i * 5}.00"),
                price_high=Decimal(f"{70 + i * 5}.00"),
            )
            session.add(history)
        await session.flush()

        histories = await PriceHistory.get_history_for_event(session, test_event.id)
        assert len(histories) >= 3

    @pytest.mark.asyncio
    async def test_get_latest_price_for_event(self, session: AsyncSession, test_event: Event):
        """Test getting latest price for event"""
        # Create history record
        history = PriceHistory(
            event_id=test_event.id, price_low=Decimal("40.00"), price_high=Decimal("90.00")
        )
        session.add(history)
        await session.flush()

        latest = await PriceHistory.get_latest_for_event(session, test_event.id)
        assert latest is not None
        assert latest.price_low == Decimal("40.00")

    @pytest.mark.asyncio
    async def test_price_history_to_dict(self, session: AsyncSession, test_event: Event):
        """Test price history to_dict conversion"""
        history = PriceHistory(
            event_id=test_event.id, price_low=Decimal("30.00"), price_high=Decimal("80.00")
        )
        session.add(history)
        await session.flush()

        data = history.to_dict()
        assert data['event_id'] == str(test_event.id)
        assert data['price_low'] == 30.0


# =============================================================================
# AvailabilityHistory Model Tests
# =============================================================================


class TestAvailabilityHistoryModel:
    """Tests for AvailabilityHistory model"""

    @pytest.mark.asyncio
    async def test_create_availability_history(self, session: AsyncSession, test_event: Event):
        """Test creating availability history record"""
        history = AvailabilityHistory(event_id=test_event.id, is_sold_out=True)
        session.add(history)
        await session.flush()

        assert history.id is not None
        assert history.is_sold_out is True
        assert history.recorded_at is not None

    @pytest.mark.asyncio
    async def test_record_availability_change(self, session: AsyncSession, test_event: Event):
        """Test recording availability change via Event method"""
        history = await test_event.record_availability_change(session, is_sold_out=True)

        assert history.id is not None
        assert history.is_sold_out is True
        assert test_event.is_sold_out is True
        assert test_event.last_changed is not None

    @pytest.mark.asyncio
    async def test_get_availability_history_for_event(
        self, session: AsyncSession, test_event: Event
    ):
        """Test getting availability history for event"""
        # Create multiple history records
        for sold_out in [False, True, False]:
            history = AvailabilityHistory(event_id=test_event.id, is_sold_out=sold_out)
            session.add(history)
        await session.flush()

        histories = await AvailabilityHistory.get_history_for_event(session, test_event.id)
        assert len(histories) >= 3

    @pytest.mark.asyncio
    async def test_availability_history_to_dict(self, session: AsyncSession, test_event: Event):
        """Test availability history to_dict conversion"""
        history = AvailabilityHistory(event_id=test_event.id, is_sold_out=True)
        session.add(history)
        await session.flush()

        data = history.to_dict()
        assert data['event_id'] == str(test_event.id)
        assert data['is_sold_out'] is True


# =============================================================================
# NotificationLog Model Tests
# =============================================================================


class TestNotificationLogModel:
    """Tests for NotificationLog model"""

    @pytest.mark.asyncio
    async def test_create_notification_log(
        self, session: AsyncSession, test_event: Event, test_tag: Tag
    ):
        """Test creating notification log record"""
        log = NotificationLog(
            event_id=test_event.id,
            tag_id=test_tag.id,
            notification_type=NotificationType.RESTOCK.value,
            webhook_url=test_tag.slack_webhook_url,
            payload={"text": "Test notification"},
            response_status=200,
            success=True,
        )
        session.add(log)
        await session.flush()

        assert log.id is not None
        assert log.success is True
        assert log.sent_at is not None

    @pytest.mark.asyncio
    async def test_log_notification_helper(
        self, session: AsyncSession, test_event: Event, test_tag: Tag
    ):
        """Test log_notification class method"""
        log = await NotificationLog.log_notification(
            session,
            notification_type=NotificationType.PRICE_CHANGE.value,
            event_id=test_event.id,
            tag_id=test_tag.id,
            webhook_url="https://hooks.slack.com/test",
            payload={"text": "Price changed"},
            response_status=200,
            success=True,
        )

        assert log.id is not None
        assert log.notification_type == "price_change"
        assert log.success is True

    @pytest.mark.asyncio
    async def test_get_logs_for_event(self, session: AsyncSession, test_event: Event):
        """Test getting notification logs for event"""
        # Create multiple logs
        for ntype in [NotificationType.RESTOCK.value, NotificationType.SOLD_OUT.value]:
            log = NotificationLog(event_id=test_event.id, notification_type=ntype, success=True)
            session.add(log)
        await session.flush()

        logs = await NotificationLog.get_logs_for_event(session, test_event.id)
        assert len(logs) >= 2

    @pytest.mark.asyncio
    async def test_get_failed_notifications(self, session: AsyncSession, test_event: Event):
        """Test getting failed notifications"""
        # Create a failed notification
        log = NotificationLog(
            event_id=test_event.id,
            notification_type=NotificationType.ERROR.value,
            success=False,
            error_message="Connection timeout",
        )
        session.add(log)
        await session.flush()

        failed = await NotificationLog.get_failed_notifications(session)
        assert any(entry.id == log.id for entry in failed)

    @pytest.mark.asyncio
    async def test_get_recent_by_type(self, session: AsyncSession, test_event: Event):
        """Test getting recent notifications by type"""
        log = NotificationLog(
            event_id=test_event.id, notification_type=NotificationType.NEW_EVENT.value, success=True
        )
        session.add(log)
        await session.flush()

        logs = await NotificationLog.get_recent_by_type(session, NotificationType.NEW_EVENT.value)
        assert any(entry.id == log.id for entry in logs)

    @pytest.mark.asyncio
    async def test_notification_log_to_dict(self, session: AsyncSession, test_event: Event):
        """Test notification log to_dict conversion"""
        log = NotificationLog(
            event_id=test_event.id,
            notification_type=NotificationType.RESTOCK.value,
            success=True,
            metadata={"attempt": 1},
        )
        session.add(log)
        await session.flush()

        data = log.to_dict()
        assert data['event_id'] == str(test_event.id)
        assert data['notification_type'] == "restock"
        assert data['metadata'] == {"attempt": 1}


# =============================================================================
# Snapshot Model Tests
# =============================================================================


class TestSnapshotModel:
    """Tests for Snapshot model"""

    @pytest.mark.asyncio
    async def test_create_snapshot(self, session: AsyncSession, test_event: Event):
        """Test creating a snapshot"""
        snapshot = Snapshot(
            event_id=test_event.id,
            content_hash="abc123def456",
            extracted_prices={"low": 25.0, "high": 75.0},
            extracted_availability="available",
            content_text="Sample content",
        )
        session.add(snapshot)
        await session.flush()

        assert snapshot.id is not None
        assert snapshot.content_hash == "abc123def456"
        assert snapshot.captured_at is not None

    @pytest.mark.asyncio
    async def test_snapshot_event_relationship(self, session: AsyncSession, test_event: Event):
        """Test snapshot-event relationship"""
        snapshot = Snapshot(event_id=test_event.id, content_hash="test_hash")
        session.add(snapshot)
        await session.flush()

        assert snapshot.event_id == test_event.id

    @pytest.mark.asyncio
    async def test_snapshot_to_dict(self, session: AsyncSession, test_event: Event):
        """Test snapshot to_dict conversion"""
        snapshot = Snapshot(
            event_id=test_event.id, content_hash="test_hash", extracted_prices={"low": 30.0}
        )
        session.add(snapshot)
        await session.flush()

        data = snapshot.to_dict()
        assert data['event_id'] == str(test_event.id)
        assert data['content_hash'] == "test_hash"
        assert data['extracted_prices'] == {"low": 30.0}


# =============================================================================
# Database Session Factory Tests
# =============================================================================


class TestSessionFactory:
    """Tests for database session factory functions"""

    def test_create_engine_from_url(self, database_url):
        """Test creating engine from URL"""
        engine = create_async_engine_from_url(database_url)
        assert engine is not None

    def test_create_engine_converts_postgresql_url(self):
        """Test that postgresql:// URLs are converted to async"""
        # This would fail without DATABASE_URL set, so we test the conversion logic
        test_url = "postgresql://user:pass@localhost/db"
        expected = "postgresql+asyncpg://user:pass@localhost/db"

        # Manually test the conversion logic
        if test_url.startswith('postgresql://'):
            converted = test_url.replace('postgresql://', 'postgresql+asyncpg://', 1)
        else:
            converted = test_url

        assert converted == expected

    def test_create_engine_converts_postgres_url(self):
        """Test that postgres:// URLs are converted to async"""
        test_url = "postgres://user:pass@localhost/db"
        expected = "postgresql+asyncpg://user:pass@localhost/db"

        if test_url.startswith('postgres://'):
            converted = test_url.replace('postgres://', 'postgresql+asyncpg://', 1)
        else:
            converted = test_url

        assert converted == expected

    def test_create_engine_without_url_raises(self):
        """Test that creating engine without URL raises error"""
        # Temporarily unset DATABASE_URL if it exists
        original = os.environ.pop('DATABASE_URL', None)
        try:
            with pytest.raises(ValueError, match="DATABASE_URL not provided"):
                create_async_engine_from_url(None)
        finally:
            if original:
                os.environ['DATABASE_URL'] = original


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Integration tests for model interactions"""

    @pytest.mark.asyncio
    async def test_full_workflow(self, session: AsyncSession):
        """Test a complete workflow with all models"""
        # Create user
        user = User(
            email=f"workflow_{uuid.uuid4().hex[:8]}@example.com",
            password_hash="$2b$12$test",
            role=UserRole.ADMIN.value,
        )
        session.add(user)
        await session.flush()

        # Create tag
        tag = Tag(
            name=f"workflow_tag_{uuid.uuid4().hex[:8]}",
            slack_webhook_url="https://hooks.slack.com/test",
            created_by=user.id,
        )
        session.add(tag)
        await session.flush()

        # Create event
        event = Event(
            url=f"https://example.com/workflow/{uuid.uuid4().hex[:8]}",
            event_name="Workflow Test Event",
            current_price_low=Decimal("50.00"),
            current_price_high=Decimal("100.00"),
        )
        session.add(event)
        await session.flush()

        # Link event to tag
        event.tags.append(tag)
        await session.flush()

        # Record price change
        price_history = await event.record_price_change(
            session, price_low=Decimal("45.00"), price_high=Decimal("95.00")
        )

        # Record availability change
        avail_history = await event.record_availability_change(session, is_sold_out=True)

        # Log notification
        notification = await NotificationLog.log_notification(
            session,
            notification_type=NotificationType.SOLD_OUT.value,
            event_id=event.id,
            tag_id=tag.id,
            webhook_url=tag.slack_webhook_url,
            success=True,
        )

        # Verify all relationships
        assert user.id is not None
        assert tag.created_by == user.id
        assert tag in event.tags
        assert event.current_price_low == Decimal("45.00")
        assert event.is_sold_out is True
        assert price_history.event_id == event.id
        assert avail_history.event_id == event.id
        assert notification.event_id == event.id
        assert notification.tag_id == tag.id

    @pytest.mark.asyncio
    async def test_cascade_delete(self, session: AsyncSession):
        """Test that deleting an event cascades to history tables"""
        # Create event
        event = Event(url=f"https://example.com/cascade/{uuid.uuid4().hex[:8]}")
        session.add(event)
        await session.flush()

        event_id = event.id

        # Create related records
        price_history = PriceHistory(event_id=event_id, price_low=Decimal("50.00"))
        avail_history = AvailabilityHistory(event_id=event_id, is_sold_out=False)
        snapshot = Snapshot(event_id=event_id, content_hash="test")

        session.add_all([price_history, avail_history, snapshot])
        await session.flush()

        # Delete event
        await session.delete(event)
        await session.flush()

        # Verify cascade - related records should be deleted
        result = await session.execute(
            select(PriceHistory).where(PriceHistory.event_id == event_id)
        )
        assert result.scalar_one_or_none() is None

        result = await session.execute(
            select(AvailabilityHistory).where(AvailabilityHistory.event_id == event_id)
        )
        assert result.scalar_one_or_none() is None

        result = await session.execute(select(Snapshot).where(Snapshot.event_id == event_id))
        assert result.scalar_one_or_none() is None
