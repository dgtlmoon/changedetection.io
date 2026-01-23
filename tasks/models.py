"""
SQLAlchemy ORM Models for ATC Page Monitor

This module provides SQLAlchemy ORM models that map to the PostgreSQL schema v2.
Models include proper relationships, helper methods, and async session support.

Usage:
    from tasks.models import User, Tag, Event, PriceHistory, AvailabilityHistory, NotificationLog
    from tasks.models import async_session_factory, create_async_engine_from_url

    # Create async engine and session
    engine = create_async_engine_from_url(os.getenv('DATABASE_URL'))
    async_session = async_session_factory(engine)

    async with async_session() as session:
        user = await User.get_by_email(session, 'admin@example.com')
"""

import os
import re
import uuid
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Table,
    Text,
    Time,
    and_,
    func,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncAttrs, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, selectinload

# =============================================================================
# Enums
# =============================================================================


class UserRole(str, Enum):
    """User roles for access control"""

    ADMIN = "admin"
    VIEWER = "viewer"


class NotificationType(str, Enum):
    """Types of notifications sent"""

    RESTOCK = "restock"
    PRICE_CHANGE = "price_change"
    SOLD_OUT = "sold_out"
    NEW_EVENT = "new_event"
    ERROR = "error"


# =============================================================================
# Slack Webhook URL Validation
# =============================================================================

# Slack webhook URL pattern: https://hooks.slack.com/services/T.../B.../...
SLACK_WEBHOOK_PATTERN = re.compile(
    r'^https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+$'
)


class SlackWebhookValidationError(ValueError):
    """Raised when a Slack webhook URL is invalid."""

    pass


def validate_slack_webhook_url(url: str | None) -> str | None:
    """
    Validate a Slack webhook URL.

    Slack webhook URLs follow the pattern:
    https://hooks.slack.com/services/T<TEAM_ID>/B<BOT_ID>/<TOKEN>

    Args:
        url: The webhook URL to validate. None or empty string is allowed
             (for clearing the webhook).

    Returns:
        The validated URL (stripped of whitespace), or None if empty.

    Raises:
        SlackWebhookValidationError: If the URL is not a valid Slack webhook URL.

    Examples:
        >>> validate_slack_webhook_url("https://hooks.slack.com/services/T123/B456/abc123")
        'https://hooks.slack.com/services/T123/B456/abc123'
        >>> validate_slack_webhook_url(None)
        None
        >>> validate_slack_webhook_url("")
        None
        >>> validate_slack_webhook_url("https://example.com")
        SlackWebhookValidationError: Invalid Slack webhook URL format
    """
    if url is None or url.strip() == '':
        return None

    url = url.strip()

    if not SLACK_WEBHOOK_PATTERN.match(url):
        raise SlackWebhookValidationError(
            f"Invalid Slack webhook URL format. Expected: "
            f"https://hooks.slack.com/services/T<TEAM_ID>/B<BOT_ID>/<TOKEN>"
        )

    return url


# =============================================================================
# Base Model
# =============================================================================


class Base(AsyncAttrs, DeclarativeBase):
    """Base class for all models with async support"""

    pass


# =============================================================================
# Association Table for Event-Tag Many-to-Many
# =============================================================================

event_tags = Table(
    'event_tags',
    Base.metadata,
    Column(
        'event_id',
        UUID(as_uuid=True),
        ForeignKey('events.id', ondelete='CASCADE'),
        primary_key=True,
    ),
    Column(
        'tag_id', UUID(as_uuid=True), ForeignKey('tags.id', ondelete='CASCADE'), primary_key=True
    ),
    Column('assigned_at', DateTime(timezone=True), default=func.now()),
    Column(
        'assigned_by',
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    ),
)


# =============================================================================
# User Model
# =============================================================================


class User(Base):
    """
    User model with role-based permissions.

    Roles:
        - admin: Full access to all features
        - viewer: Read-only access

    Attributes:
        id: UUID primary key
        email: Unique email address
        password_hash: Bcrypt hashed password
        role: User role (admin or viewer)
        created_at: Account creation timestamp
        last_login: Last login timestamp
        is_active: Account active status
    """

    __tablename__ = 'users'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, default=UserRole.VIEWER.value)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=func.now())
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    created_tags: Mapped[list["Tag"]] = relationship(
        "Tag", back_populates="creator", foreign_keys="Tag.created_by"
    )

    __table_args__ = (
        CheckConstraint("role IN ('admin', 'viewer')", name='users_role_check'),
        CheckConstraint("email <> ''", name='users_email_not_empty'),
        CheckConstraint("password_hash <> ''", name='users_password_hash_not_empty'),
    )

    # -------------------------------------------------------------------------
    # Role-based permission methods
    # -------------------------------------------------------------------------

    def is_admin(self) -> bool:
        """Check if user has admin role"""
        return self.role == UserRole.ADMIN.value

    def is_viewer(self) -> bool:
        """Check if user has viewer role"""
        return self.role == UserRole.VIEWER.value

    def can_edit(self) -> bool:
        """Check if user can edit resources (admin only)"""
        return self.is_admin()

    def can_view(self) -> bool:
        """Check if user can view resources (all active users)"""
        return self.is_active

    def can_manage_users(self) -> bool:
        """Check if user can manage other users (admin only)"""
        return self.is_admin()

    def can_manage_tags(self) -> bool:
        """Check if user can create/edit tags (admin only)"""
        return self.is_admin()

    def can_manage_events(self) -> bool:
        """Check if user can create/edit events (admin only)"""
        return self.is_admin()

    # -------------------------------------------------------------------------
    # Class methods for common queries
    # -------------------------------------------------------------------------

    @classmethod
    async def get_by_email(cls, session: AsyncSession, email: str) -> Optional["User"]:
        """Get user by email address"""
        result = await session.execute(select(cls).where(cls.email == email))
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_id(cls, session: AsyncSession, user_id: uuid.UUID) -> Optional["User"]:
        """Get user by ID"""
        result = await session.execute(select(cls).where(cls.id == user_id))
        return result.scalar_one_or_none()

    @classmethod
    async def get_active_users(cls, session: AsyncSession) -> list["User"]:
        """Get all active users"""
        result = await session.execute(select(cls).where(cls.is_active.is_(True)))
        return list(result.scalars().all())

    @classmethod
    async def get_admins(cls, session: AsyncSession) -> list["User"]:
        """Get all admin users"""
        result = await session.execute(
            select(cls).where(and_(cls.role == UserRole.ADMIN.value, cls.is_active.is_(True)))
        )
        return list(result.scalars().all())

    async def update_last_login(self, session: AsyncSession) -> None:
        """Update last login timestamp"""
        self.last_login = datetime.now()
        await session.commit()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': str(self.id),
            'email': self.email,
            'role': self.role,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'is_active': self.is_active,
        }


# =============================================================================
# Tag Model
# =============================================================================


class Tag(Base):
    """
    Tag model for categorizing events with Slack webhook routing.

    Attributes:
        id: UUID primary key
        name: Unique tag name
        slack_webhook_url: Optional Slack webhook for notifications
        notification_muted: Whether notifications are muted for this tag
        color: Display color (hex)
        created_at: Creation timestamp
        created_by: User who created the tag
    """

    __tablename__ = 'tags'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    slack_webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    notification_muted: Mapped[bool] = mapped_column(Boolean, default=False)
    color: Mapped[str] = mapped_column(Text, default='#3B82F6')
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=func.now())
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    )

    # Relationships
    creator: Mapped[Optional["User"]] = relationship(
        "User", back_populates="created_tags", foreign_keys=[created_by]
    )
    events: Mapped[list["Event"]] = relationship(
        "Event", secondary=event_tags, back_populates="tags"
    )
    notification_logs: Mapped[list["NotificationLog"]] = relationship(
        "NotificationLog", back_populates="tag"
    )

    __table_args__ = (CheckConstraint("name <> ''", name='tags_name_not_empty'),)

    # -------------------------------------------------------------------------
    # Helper methods
    # -------------------------------------------------------------------------

    def has_webhook(self) -> bool:
        """Check if tag has a configured webhook"""
        return bool(self.slack_webhook_url)

    def can_notify(self) -> bool:
        """Check if tag can send notifications (has webhook and not muted)"""
        return self.has_webhook() and not self.notification_muted

    def set_webhook_url(self, url: str | None) -> None:
        """
        Set the Slack webhook URL with validation.

        Args:
            url: The webhook URL to set, or None to clear.

        Raises:
            SlackWebhookValidationError: If the URL is not a valid Slack webhook URL.
        """
        self.slack_webhook_url = validate_slack_webhook_url(url)

    # -------------------------------------------------------------------------
    # Class methods for common queries
    # -------------------------------------------------------------------------

    @classmethod
    async def get_by_name(cls, session: AsyncSession, name: str) -> Optional["Tag"]:
        """Get tag by name"""
        result = await session.execute(select(cls).where(cls.name == name))
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_id(cls, session: AsyncSession, tag_id: uuid.UUID) -> Optional["Tag"]:
        """Get tag by ID"""
        result = await session.execute(select(cls).where(cls.id == tag_id))
        return result.scalar_one_or_none()

    @classmethod
    async def get_tags_with_webhooks(cls, session: AsyncSession) -> list["Tag"]:
        """Get all tags that have webhook URLs configured and notifications enabled"""
        result = await session.execute(
            select(cls).where(
                and_(
                    cls.slack_webhook_url.isnot(None),
                    cls.slack_webhook_url != '',
                    cls.notification_muted.is_(False),
                )
            )
        )
        return list(result.scalars().all())

    @classmethod
    async def get_all(cls, session: AsyncSession) -> list["Tag"]:
        """Get all tags"""
        result = await session.execute(select(cls).order_by(cls.name))
        return list(result.scalars().all())

    @classmethod
    async def update_tag(
        cls,
        session: AsyncSession,
        tag_id: uuid.UUID,
        slack_webhook_url: str | None = None,
        notification_muted: bool | None = None,
        color: str | None = None,
        name: str | None = None,
    ) -> Optional["Tag"]:
        """
        Update a tag's properties with validation.

        Args:
            session: Database session
            tag_id: UUID of the tag to update
            slack_webhook_url: New webhook URL (validated) or None to clear
            notification_muted: Whether to mute notifications
            color: New color (hex format)
            name: New tag name

        Returns:
            Updated Tag object, or None if tag not found.

        Raises:
            SlackWebhookValidationError: If the webhook URL is invalid.
        """
        tag = await cls.get_by_id(session, tag_id)
        if not tag:
            return None

        if slack_webhook_url is not None or slack_webhook_url == '':
            # Validate and set the webhook URL (None or '' clears it)
            tag.set_webhook_url(slack_webhook_url if slack_webhook_url != '' else None)

        if notification_muted is not None:
            tag.notification_muted = notification_muted

        if color is not None:
            tag.color = color

        if name is not None and name.strip():
            tag.name = name.strip()

        await session.commit()
        await session.refresh(tag)
        return tag

    @classmethod
    async def get_webhooks_for_event(
        cls, session: AsyncSession, event_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        """
        Get all active webhook URLs for an event's tags.

        Returns webhooks from tags that:
        - Have a slack_webhook_url configured
        - Are not muted (notification_muted=False)

        Args:
            session: Database session
            event_id: UUID of the event

        Returns:
            List of dicts with 'tag_id', 'tag_name', and 'webhook_url' for each
            active webhook. Events with multiple tags will return multiple webhooks.
        """
        # Import here to avoid circular import
        from tasks.models import event_tags as event_tags_table

        result = await session.execute(
            select(cls)
            .join(event_tags_table, event_tags_table.c.tag_id == cls.id)
            .where(
                and_(
                    event_tags_table.c.event_id == event_id,
                    cls.slack_webhook_url.isnot(None),
                    cls.slack_webhook_url != '',
                    cls.notification_muted.is_(False),
                )
            )
        )
        tags = result.scalars().all()

        return [
            {
                'tag_id': str(tag.id),
                'tag_name': tag.name,
                'webhook_url': tag.slack_webhook_url,
            }
            for tag in tags
        ]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': str(self.id),
            'name': self.name,
            'slack_webhook_url': self.slack_webhook_url,
            'notification_muted': self.notification_muted,
            'color': self.color,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'created_by': str(self.created_by) if self.created_by else None,
        }


# =============================================================================
# Event Model
# =============================================================================


class Event(Base):
    """
    Event model with full ticketing data extraction fields.

    Attributes:
        id: UUID primary key
        url: Unique URL being monitored
        event_name: Name of the event
        artist: Artist/performer name
        venue: Venue name
        event_date: Date of the event
        event_time: Time of the event
        current_price_low: Lowest current ticket price
        current_price_high: Highest current ticket price
        is_sold_out: Whether tickets are sold out
        ticket_types: JSONB list of ticket types
        track_specific_types: Whether to track specific ticket types
        check_interval: Seconds between checks
        paused: Whether monitoring is paused
        include_filters: JSONB list of include filters
        css_selectors: JSONB dict of CSS selectors
        headers: JSONB dict of request headers
        fetch_backend: Backend for fetching (playwright, requests, etc.)
        processor: Processor type
        created_at: Creation timestamp
        last_checked: Last check timestamp
        last_changed: Last change detected timestamp
        extra_config: JSONB extensible config
        notification_urls: JSONB list of notification URLs
    """

    __tablename__ = 'events'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    event_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    artist: Mapped[str | None] = mapped_column(Text, nullable=True)
    venue: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    event_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    current_price_low: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    current_price_high: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    is_sold_out: Mapped[bool] = mapped_column(Boolean, default=False)
    ticket_types: Mapped[list | None] = mapped_column(JSONB, default=list)
    track_specific_types: Mapped[bool] = mapped_column(Boolean, default=False)
    check_interval: Mapped[int] = mapped_column(Integer, default=3600)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    include_filters: Mapped[list | None] = mapped_column(JSONB, default=list)
    css_selectors: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    headers: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    fetch_backend: Mapped[str] = mapped_column(Text, default='playwright')
    processor: Mapped[str] = mapped_column(Text, default='text_json_diff')
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=func.now())
    last_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_changed: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extra_config: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    notification_urls: Mapped[list | None] = mapped_column(JSONB, default=list)

    # Relationships
    tags: Mapped[list["Tag"]] = relationship("Tag", secondary=event_tags, back_populates="events")
    price_history: Mapped[list["PriceHistory"]] = relationship(
        "PriceHistory", back_populates="event", cascade="all, delete-orphan"
    )
    availability_history: Mapped[list["AvailabilityHistory"]] = relationship(
        "AvailabilityHistory", back_populates="event", cascade="all, delete-orphan"
    )
    notification_logs: Mapped[list["NotificationLog"]] = relationship(
        "NotificationLog", back_populates="event"
    )
    snapshots: Mapped[list["Snapshot"]] = relationship(
        "Snapshot", back_populates="event", cascade="all, delete-orphan"
    )

    __table_args__ = (CheckConstraint("url <> ''", name='events_url_not_empty'),)

    # -------------------------------------------------------------------------
    # Helper methods
    # -------------------------------------------------------------------------

    def needs_check(self) -> bool:
        """Check if event needs to be checked based on interval"""
        if self.paused:
            return False
        if self.last_checked is None:
            return True
        elapsed = (datetime.now() - self.last_checked).total_seconds()
        return elapsed >= self.check_interval

    def get_price_range_str(self) -> str | None:
        """Get formatted price range string"""
        if self.current_price_low is None and self.current_price_high is None:
            return None
        if self.current_price_low == self.current_price_high:
            return f"${self.current_price_low:.2f}"
        return f"${self.current_price_low:.2f} - ${self.current_price_high:.2f}"

    # -------------------------------------------------------------------------
    # Class methods for common queries
    # -------------------------------------------------------------------------

    @classmethod
    async def get_by_url(cls, session: AsyncSession, url: str) -> Optional["Event"]:
        """Get event by URL"""
        result = await session.execute(select(cls).where(cls.url == url))
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_id(cls, session: AsyncSession, event_id: uuid.UUID) -> Optional["Event"]:
        """Get event by ID with relationships loaded"""
        result = await session.execute(
            select(cls)
            .where(cls.id == event_id)
            .options(selectinload(cls.tags), selectinload(cls.price_history))
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_active_events(cls, session: AsyncSession) -> list["Event"]:
        """Get all non-paused events"""
        result = await session.execute(select(cls).where(cls.paused.is_(False)))
        return list(result.scalars().all())

    @classmethod
    async def get_events_needing_check(cls, session: AsyncSession) -> list["Event"]:
        """Get events that need to be checked based on their check interval"""
        result = await session.execute(
            select(cls).where(
                and_(
                    cls.paused.is_(False),
                    or_(
                        cls.last_checked.is_(None),
                        func.extract('epoch', func.now() - cls.last_checked) >= cls.check_interval,
                    ),
                )
            )
        )
        return list(result.scalars().all())

    @classmethod
    async def get_events_by_tag(cls, session: AsyncSession, tag_id: uuid.UUID) -> list["Event"]:
        """Get all events with a specific tag"""
        result = await session.execute(
            select(cls).join(event_tags).where(event_tags.c.tag_id == tag_id)
        )
        return list(result.scalars().all())

    @classmethod
    async def get_sold_out_events(cls, session: AsyncSession) -> list["Event"]:
        """Get all events that are sold out"""
        result = await session.execute(select(cls).where(cls.is_sold_out.is_(True)))
        return list(result.scalars().all())

    @classmethod
    async def get_available_events(cls, session: AsyncSession) -> list["Event"]:
        """Get all events that are not sold out"""
        result = await session.execute(select(cls).where(cls.is_sold_out.is_(False)))
        return list(result.scalars().all())

    async def record_price_change(
        self,
        session: AsyncSession,
        price_low: Decimal | None = None,
        price_high: Decimal | None = None,
        ticket_type: str | None = None,
    ) -> "PriceHistory":
        """
        Record a price change for this event.

        Creates a new PriceHistory record and updates current prices.
        """
        # Create price history record
        history = PriceHistory(
            event_id=self.id, price_low=price_low, price_high=price_high, ticket_type=ticket_type
        )
        session.add(history)

        # Update current prices
        if price_low is not None:
            self.current_price_low = price_low
        if price_high is not None:
            self.current_price_high = price_high
        self.last_changed = datetime.now()

        await session.commit()
        return history

    async def record_availability_change(
        self, session: AsyncSession, is_sold_out: bool
    ) -> "AvailabilityHistory":
        """
        Record an availability change for this event.

        Creates a new AvailabilityHistory record and updates current status.
        """
        history = AvailabilityHistory(event_id=self.id, is_sold_out=is_sold_out)
        session.add(history)

        self.is_sold_out = is_sold_out
        self.last_changed = datetime.now()

        await session.commit()
        return history

    async def mark_checked(self, session: AsyncSession) -> None:
        """Update last_checked timestamp"""
        self.last_checked = datetime.now()
        await session.commit()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': str(self.id),
            'url': self.url,
            'event_name': self.event_name,
            'artist': self.artist,
            'venue': self.venue,
            'event_date': self.event_date.isoformat() if self.event_date else None,
            'event_time': self.event_time.isoformat() if self.event_time else None,
            'current_price_low': float(self.current_price_low) if self.current_price_low else None,
            'current_price_high': float(self.current_price_high)
            if self.current_price_high
            else None,
            'is_sold_out': self.is_sold_out,
            'ticket_types': self.ticket_types,
            'track_specific_types': self.track_specific_types,
            'check_interval': self.check_interval,
            'paused': self.paused,
            'include_filters': self.include_filters,
            'css_selectors': self.css_selectors,
            'headers': self.headers,
            'fetch_backend': self.fetch_backend,
            'processor': self.processor,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_checked': self.last_checked.isoformat() if self.last_checked else None,
            'last_changed': self.last_changed.isoformat() if self.last_changed else None,
            'extra_config': self.extra_config,
            'notification_urls': self.notification_urls,
        }


# =============================================================================
# PriceHistory Model
# =============================================================================


class PriceHistory(Base):
    """
    Price history tracking for events.

    Records price changes over time for analysis and notifications.

    Attributes:
        id: UUID primary key
        event_id: Foreign key to Event
        price_low: Low price at this point in time
        price_high: High price at this point in time
        ticket_type: Optional ticket type for price
        recorded_at: When this price was recorded
    """

    __tablename__ = 'price_history'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey('events.id', ondelete='CASCADE'), nullable=False
    )
    price_low: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    price_high: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    ticket_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=func.now()
    )

    # Relationships
    event: Mapped["Event"] = relationship("Event", back_populates="price_history")

    # -------------------------------------------------------------------------
    # Class methods for common queries
    # -------------------------------------------------------------------------

    @classmethod
    async def get_history_for_event(
        cls, session: AsyncSession, event_id: uuid.UUID, limit: int = 100
    ) -> list["PriceHistory"]:
        """Get price history for an event, most recent first"""
        result = await session.execute(
            select(cls)
            .where(cls.event_id == event_id)
            .order_by(cls.recorded_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    @classmethod
    async def get_latest_for_event(
        cls, session: AsyncSession, event_id: uuid.UUID
    ) -> Optional["PriceHistory"]:
        """Get the most recent price history entry for an event"""
        result = await session.execute(
            select(cls).where(cls.event_id == event_id).order_by(cls.recorded_at.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': str(self.id),
            'event_id': str(self.event_id),
            'price_low': float(self.price_low) if self.price_low else None,
            'price_high': float(self.price_high) if self.price_high else None,
            'ticket_type': self.ticket_type,
            'recorded_at': self.recorded_at.isoformat() if self.recorded_at else None,
        }


# =============================================================================
# AvailabilityHistory Model
# =============================================================================


class AvailabilityHistory(Base):
    """
    Availability history tracking for events.

    Records sold out/available state changes over time.

    Attributes:
        id: UUID primary key
        event_id: Foreign key to Event
        is_sold_out: Whether event was sold out at this point
        recorded_at: When this status was recorded
    """

    __tablename__ = 'availability_history'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey('events.id', ondelete='CASCADE'), nullable=False
    )
    is_sold_out: Mapped[bool] = mapped_column(Boolean, nullable=False)
    recorded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=func.now()
    )

    # Relationships
    event: Mapped["Event"] = relationship("Event", back_populates="availability_history")

    # -------------------------------------------------------------------------
    # Class methods for common queries
    # -------------------------------------------------------------------------

    @classmethod
    async def get_history_for_event(
        cls, session: AsyncSession, event_id: uuid.UUID, limit: int = 100
    ) -> list["AvailabilityHistory"]:
        """Get availability history for an event, most recent first"""
        result = await session.execute(
            select(cls)
            .where(cls.event_id == event_id)
            .order_by(cls.recorded_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    @classmethod
    async def get_latest_for_event(
        cls, session: AsyncSession, event_id: uuid.UUID
    ) -> Optional["AvailabilityHistory"]:
        """Get the most recent availability history entry for an event"""
        result = await session.execute(
            select(cls).where(cls.event_id == event_id).order_by(cls.recorded_at.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_restock_events(
        cls, session: AsyncSession, since: datetime | None = None
    ) -> list["AvailabilityHistory"]:
        """Get events that went from sold out to available (restocks)"""
        # This is a more complex query that would need window functions
        # For simplicity, we return recent availability changes to not sold out
        query = select(cls).where(cls.is_sold_out.is_(False))
        if since:
            query = query.where(cls.recorded_at >= since)
        query = query.order_by(cls.recorded_at.desc())
        result = await session.execute(query)
        return list(result.scalars().all())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': str(self.id),
            'event_id': str(self.event_id),
            'is_sold_out': self.is_sold_out,
            'recorded_at': self.recorded_at.isoformat() if self.recorded_at else None,
        }


# =============================================================================
# NotificationLog Model
# =============================================================================


class NotificationLog(Base):
    """
    Notification log for tracking sent notifications.

    Records all notifications sent for auditing and debugging.

    Attributes:
        id: UUID primary key
        event_id: Foreign key to Event (optional)
        tag_id: Foreign key to Tag (optional)
        notification_type: Type of notification (restock, price_change, etc.)
        webhook_url: URL the notification was sent to
        payload: JSONB payload sent
        response_status: HTTP response status code
        response_body: HTTP response body
        success: Whether notification was successful
        error_message: Error message if failed
        sent_at: When notification was sent
        metadata: JSONB additional metadata
    """

    __tablename__ = 'notification_log'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey('events.id', ondelete='SET NULL'), nullable=True
    )
    tag_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey('tags.id', ondelete='SET NULL'), nullable=True
    )
    notification_type: Mapped[str] = mapped_column(Text, nullable=False)
    webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=func.now())
    extra_metadata: Mapped[dict | None] = mapped_column('metadata', JSONB, default=dict)

    # Relationships
    event: Mapped[Optional["Event"]] = relationship("Event", back_populates="notification_logs")
    tag: Mapped[Optional["Tag"]] = relationship("Tag", back_populates="notification_logs")

    __table_args__ = (
        CheckConstraint(
            "notification_type IN ('restock', 'price_change', 'sold_out', 'new_event', 'error')",
            name='notification_log_type_check',
        ),
    )

    # -------------------------------------------------------------------------
    # Class methods for common queries
    # -------------------------------------------------------------------------

    @classmethod
    async def get_logs_for_event(
        cls, session: AsyncSession, event_id: uuid.UUID, limit: int = 100
    ) -> list["NotificationLog"]:
        """Get notification logs for an event, most recent first"""
        result = await session.execute(
            select(cls).where(cls.event_id == event_id).order_by(cls.sent_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    @classmethod
    async def get_logs_for_tag(
        cls, session: AsyncSession, tag_id: uuid.UUID, limit: int = 100
    ) -> list["NotificationLog"]:
        """Get notification logs for a tag, most recent first"""
        result = await session.execute(
            select(cls).where(cls.tag_id == tag_id).order_by(cls.sent_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    @classmethod
    async def get_failed_notifications(
        cls, session: AsyncSession, since: datetime | None = None, limit: int = 100
    ) -> list["NotificationLog"]:
        """Get failed notifications"""
        query = select(cls).where(cls.success.is_(False))
        if since:
            query = query.where(cls.sent_at >= since)
        query = query.order_by(cls.sent_at.desc()).limit(limit)
        result = await session.execute(query)
        return list(result.scalars().all())

    @classmethod
    async def get_recent_by_type(
        cls, session: AsyncSession, notification_type: str, limit: int = 100
    ) -> list["NotificationLog"]:
        """Get recent notifications of a specific type"""
        result = await session.execute(
            select(cls)
            .where(cls.notification_type == notification_type)
            .order_by(cls.sent_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    @classmethod
    async def log_notification(
        cls,
        session: AsyncSession,
        notification_type: str,
        event_id: uuid.UUID | None = None,
        tag_id: uuid.UUID | None = None,
        webhook_url: str | None = None,
        payload: dict | None = None,
        response_status: int | None = None,
        response_body: str | None = None,
        success: bool = False,
        error_message: str | None = None,
        metadata: dict | None = None,
    ) -> "NotificationLog":
        """Create a new notification log entry"""
        log = cls(
            event_id=event_id,
            tag_id=tag_id,
            notification_type=notification_type,
            webhook_url=webhook_url,
            payload=payload,
            response_status=response_status,
            response_body=response_body,
            success=success,
            error_message=error_message,
            extra_metadata=metadata or {},
        )
        session.add(log)
        await session.commit()
        return log

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': str(self.id),
            'event_id': str(self.event_id) if self.event_id else None,
            'tag_id': str(self.tag_id) if self.tag_id else None,
            'notification_type': self.notification_type,
            'webhook_url': self.webhook_url,
            'payload': self.payload,
            'response_status': self.response_status,
            'response_body': self.response_body,
            'success': self.success,
            'error_message': self.error_message,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'metadata': self.extra_metadata,
        }


# =============================================================================
# Snapshot Model (Legacy Compatibility)
# =============================================================================


class Snapshot(Base):
    """
    Snapshot model for legacy compatibility.

    Stores content snapshots for change detection.

    Attributes:
        id: UUID primary key
        event_id: Foreign key to Event
        content_hash: Hash of the content
        captured_at: When snapshot was captured
        extracted_prices: JSONB extracted price data
        extracted_availability: Extracted availability status
        content_text: Full text content
        content_url: URL of content source
    """

    __tablename__ = 'snapshots'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey('events.id', ondelete='CASCADE'), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=func.now()
    )
    extracted_prices: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    extracted_availability: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    event: Mapped["Event"] = relationship("Event", back_populates="snapshots")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': str(self.id),
            'event_id': str(self.event_id),
            'content_hash': self.content_hash,
            'captured_at': self.captured_at.isoformat() if self.captured_at else None,
            'extracted_prices': self.extracted_prices,
            'extracted_availability': self.extracted_availability,
            'content_text': self.content_text,
            'content_url': self.content_url,
        }


# =============================================================================
# Database Session Factory
# =============================================================================


def create_async_engine_from_url(database_url: str | None = None):
    """
    Create an async SQLAlchemy engine from a database URL.

    Args:
        database_url: PostgreSQL connection URL. If not provided,
                     reads from DATABASE_URL environment variable.

    Returns:
        AsyncEngine instance
    """
    url = database_url or os.getenv('DATABASE_URL')
    if not url:
        raise ValueError("DATABASE_URL not provided and not set in environment")

    # Convert postgresql:// to postgresql+asyncpg:// for async support
    if url.startswith('postgresql://'):
        url = url.replace('postgresql://', 'postgresql+asyncpg://', 1)
    elif url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql+asyncpg://', 1)

    return create_async_engine(url, echo=False)


def async_session_factory(engine) -> async_sessionmaker[AsyncSession]:
    """
    Create an async session factory from an engine.

    Args:
        engine: AsyncEngine instance

    Returns:
        async_sessionmaker instance for creating sessions
    """
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_models(engine) -> None:
    """
    Initialize models by creating all tables.

    Note: Prefer using apply_schema_v2() from schema_v2.py for production
    as it includes proper migration handling.

    Args:
        engine: AsyncEngine instance
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# =============================================================================
# CLI for Testing
# =============================================================================

if __name__ == "__main__":
    import asyncio

    async def main():
        """Test models with basic CRUD operations."""
        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            print("DATABASE_URL environment variable not set")
            print("Example: postgresql://user:password@host/database?sslmode=require")
            return

        print("Creating async engine...")
        engine = create_async_engine_from_url(database_url)
        async_session = async_session_factory(engine)

        try:
            async with async_session() as session:
                # Test User model
                print("\n--- Testing User Model ---")
                user = await User.get_by_email(session, 'admin@example.com')
                if user:
                    print(f"Found user: {user.email}, role: {user.role}")
                    print(f"  is_admin: {user.is_admin()}")
                    print(f"  can_edit: {user.can_edit()}")
                else:
                    print("Admin user not found (run apply_schema_v2 with sample data)")

                # Test Tag model
                print("\n--- Testing Tag Model ---")
                tags = await Tag.get_all(session)
                print(f"Found {len(tags)} tags")
                for tag in tags[:3]:
                    print(f"  - {tag.name} (color: {tag.color})")

                tags_with_webhooks = await Tag.get_tags_with_webhooks(session)
                print(f"Tags with webhooks: {len(tags_with_webhooks)}")

                # Test Event model
                print("\n--- Testing Event Model ---")
                events = await Event.get_active_events(session)
                print(f"Found {len(events)} active events")
                for event in events[:3]:
                    print(f"  - {event.event_name or event.url}")
                    print(f"    Price range: {event.get_price_range_str()}")
                    print(f"    Sold out: {event.is_sold_out}")

                # Test PriceHistory
                print("\n--- Testing PriceHistory Model ---")
                if events:
                    history = await PriceHistory.get_history_for_event(
                        session, events[0].id, limit=5
                    )
                    print(f"Price history for first event: {len(history)} records")

                # Test NotificationLog
                print("\n--- Testing NotificationLog Model ---")
                failed = await NotificationLog.get_failed_notifications(session, limit=5)
                print(f"Failed notifications: {len(failed)}")

                print("\nAll model tests passed!")

        finally:
            await engine.dispose()

    asyncio.run(main())
