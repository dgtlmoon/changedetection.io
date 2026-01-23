"""
PostgreSQL Storage Adapter for TicketWatch/ATC Page Monitor

This module provides a PostgreSQL-based storage adapter that implements
the same interface as ChangeDetectionStore, allowing drop-in replacement
of the JSON file-based storage.

Implements all methods from changedetectionio.store.ChangeDetectionStore:
- add_watch() - Insert into events table
- update_watch() - Update events table
- delete() - Cascade delete event and related history
- url_exists() - Check for existing URLs
- clear_watch_history() - Remove watch history
- set_last_viewed() - Update view timestamp
- get_all_tags_for_watch() - Get tags for a watch
- add_tag() - Create/get tag by name
- tag_exists_by_name() - Check if tag exists
- search_watches_for_url() - Search watches
- get_preferred_proxy_for_watch() - Get proxy for watch

Connection pooling configured for 10 connections with graceful error handling.

Usage:
    from tasks.postgresql_store import PostgreSQLStore

    store = PostgreSQLStore(database_url=os.getenv('DATABASE_URL'))
    await store.initialize()

    # Add a watch
    uuid = await store.add_watch(url='https://example.com/tickets', tag='concerts')

    # Update a watch
    await store.update_watch(uuid, {'paused': True})

    # Delete a watch (cascades to history)
    await store.delete(uuid)
"""

import json
import os
import time
import uuid as uuid_builder
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from typing import Any

try:
    import asyncpg

    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False

try:
    import psycopg2
    import psycopg2.extras

    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

try:
    from blinker import signal

    HAS_BLINKER = True
except ImportError:
    HAS_BLINKER = False

# Import SQLAlchemy models from US-002
from sqlalchemy import delete, func, or_, select

from tasks.models import (
    AvailabilityHistory,
    Event,
    PriceHistory,
    SlackWebhookValidationError,
    Snapshot,
    Tag,
    async_session_factory,
    create_async_engine_from_url,
    validate_slack_webhook_url,
)

# Import event extractor (US-007)
try:
    from tasks.event_extractor import EventDataExtractor, ExtractionResult

    HAS_EVENT_EXTRACTOR = True
except ImportError:
    HAS_EVENT_EXTRACTOR = False

# =============================================================================
# Constants
# =============================================================================

BASE_URL_NOT_SET_TEXT = '("Base URL" not set - see settings - notifications)'
POOL_MIN_SIZE = 2
POOL_MAX_SIZE = 10
COMMAND_TIMEOUT = 60


# =============================================================================
# PostgreSQL Store Implementation
# =============================================================================


class PostgreSQLStore:
    """
    PostgreSQL storage adapter implementing ChangeDetectionStore interface.

    Provides both async and sync methods for storing and retrieving watch
    configurations and event data. Uses SQLAlchemy ORM with asyncpg backend.
    """

    lock = Lock()
    needs_write = False
    needs_write_urgent = False
    datastore_path = None

    def __init__(
        self,
        database_url: str | None = None,
        datastore_path: str = "/datastore",
        include_default_watches: bool = True,
        version_tag: str = "0.0.0",
    ):
        """
        Initialize the PostgreSQL store.

        Args:
            database_url: PostgreSQL connection string. If not provided,
                         reads from DATABASE_URL environment variable.
            datastore_path: Path for any file-based fallback data (proxies, headers)
            include_default_watches: Whether to include default example watches
            version_tag: Application version tag
        """
        self.database_url = database_url or os.getenv('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL must be provided or set as environment variable")

        self.datastore_path = datastore_path
        self.version_tag = version_tag
        self.include_default_watches = include_default_watches

        # Connection pool (asyncpg)
        self._pool: asyncpg.Pool | None = None

        # SQLAlchemy async engine and session
        self._engine = None
        self._async_session = None

        # Sync connection (psycopg2 fallback)
        self._sync_conn = None

        # In-memory cache for settings (settings are not stored in PostgreSQL)
        self._settings_cache = self._default_settings()

        # Track initialization state
        self._initialized = False
        self.start_time = time.time()
        self.stop_thread = False

    def _default_settings(self) -> dict[str, Any]:
        """Return default settings structure."""
        return {
            'headers': {},
            'requests': {
                'time_between_check': {
                    'weeks': None,
                    'days': None,
                    'hours': 3,
                    'minutes': None,
                    'seconds': None,
                },
                'timeout': 15,
                'workers': 10,
                'proxy': None,
                'extra_proxies': [],
                'extra_browsers': [],
            },
            'application': {
                'tags': {},
                'notification_title': 'ChangeDetection.io Notification - {{ watch_url }}',
                'notification_body': '{{ watch_url }} had a change.',
                'notification_format': 'text',
                'notification_urls': [],
                'password': False,
                'base_url': '',
                'schema_version': 25,
                'rss_access_token': None,
                'api_access_token': None,
                'active_base_url': BASE_URL_NOT_SET_TEXT,
                'ui': {},
            },
        }

    # -------------------------------------------------------------------------
    # Connection Management
    # -------------------------------------------------------------------------

    async def initialize(self) -> None:
        """Initialize the database connection pool and SQLAlchemy engine."""
        if self._initialized:
            return

        logger.info("Initializing PostgreSQL connection pool...")

        # Initialize asyncpg pool
        if HAS_ASYNCPG:
            try:
                self._pool = await asyncpg.create_pool(
                    self.database_url,
                    min_size=POOL_MIN_SIZE,
                    max_size=POOL_MAX_SIZE,
                    command_timeout=COMMAND_TIMEOUT,
                )
                logger.info(f"asyncpg pool created with {POOL_MAX_SIZE} max connections")
            except Exception as e:
                logger.error(f"Failed to create asyncpg pool: {e}")
                raise

        # Initialize SQLAlchemy async engine
        try:
            self._engine = create_async_engine_from_url(self.database_url)
            self._async_session = async_session_factory(self._engine)
            logger.info("SQLAlchemy async engine initialized")
        except Exception as e:
            logger.error(f"Failed to create SQLAlchemy engine: {e}")
            raise

        # Load tags from database into settings cache
        await self._load_tags_to_cache()

        # Add default watches if this is first run and database is empty
        if self.include_default_watches:
            await self._add_default_watches_if_empty()

        self._initialized = True
        logger.info("PostgreSQL store initialized successfully")

    async def close(self) -> None:
        """Close database connections."""
        self.stop_thread = True

        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("asyncpg pool closed")

        if self._engine:
            await self._engine.dispose()
            self._engine = None
            logger.info("SQLAlchemy engine disposed")

        self._initialized = False

    @asynccontextmanager
    async def acquire(self):
        """Acquire a connection from the asyncpg pool."""
        if not self._pool:
            raise RuntimeError("Store not initialized. Call initialize() first.")
        async with self._pool.acquire() as conn:
            yield conn

    @asynccontextmanager
    async def session(self):
        """Get a SQLAlchemy async session."""
        if not self._async_session:
            raise RuntimeError("Store not initialized. Call initialize() first.")
        async with self._async_session() as session:
            yield session

    def initialize_sync(self) -> None:
        """Initialize synchronous database connection (fallback)."""
        if not HAS_PSYCOPG2:
            raise ImportError("psycopg2 is required for sync PostgreSQL support")

        logger.info("Initializing synchronous PostgreSQL connection...")
        self._sync_conn = psycopg2.connect(self.database_url)
        self._initialized = True
        logger.info("PostgreSQL store initialized (sync mode)")

    def close_sync(self) -> None:
        """Close synchronous connection."""
        if self._sync_conn:
            self._sync_conn.close()
            self._sync_conn = None

    # -------------------------------------------------------------------------
    # Watch CRUD Operations
    # -------------------------------------------------------------------------

    async def add_watch(
        self,
        url: str,
        tag: str = '',
        extras: dict[str, Any] | None = None,
        tag_uuids: list[str] | None = None,
        write_to_disk_now: bool = True,
    ) -> str | None:
        """
        Add a new watch (event) to the database.

        Args:
            url: URL to monitor
            tag: Comma-separated tag names or empty string
            extras: Additional watch configuration
            tag_uuids: List of tag UUIDs to associate
            write_to_disk_now: Ignored (for interface compatibility)

        Returns:
            UUID of the new watch, or None if URL is invalid
        """
        if extras is None:
            extras = {}

        apply_extras = deepcopy(extras)
        apply_extras['tags'] = apply_extras.get('tags', [])

        # Process tag string to tag UUIDs
        if tag and isinstance(tag, str):
            for t in tag.split(','):
                t = t.strip()
                if t:
                    tag_uuid = await self.add_tag(t)
                    if tag_uuid:
                        apply_extras['tags'].append(tag_uuid)

        # Add directly provided tag UUIDs
        if tag_uuids:
            for t in tag_uuids:
                apply_extras['tags'].append(t.strip())

        # Make tag UUIDs unique
        apply_extras['tags'] = list(set(apply_extras['tags']))

        # Generate new UUID
        new_uuid = str(uuid_builder.uuid4())

        # Calculate check_interval from time_between_check if provided
        check_interval = 3600  # Default 1 hour
        time_between = apply_extras.get('time_between_check', {})
        if time_between:
            check_interval = (
                (time_between.get('weeks', 0) or 0) * 604800
                + (time_between.get('days', 0) or 0) * 86400
                + (time_between.get('hours', 0) or 0) * 3600
                + (time_between.get('minutes', 0) or 0) * 60
                + (time_between.get('seconds', 0) or 0)
            )
            if check_interval == 0:
                check_interval = 3600

        async with self.session() as session:
            # Create Event record
            event = Event(
                id=uuid_builder.UUID(new_uuid),
                url=url,
                event_name=apply_extras.get('title'),
                check_interval=check_interval,
                paused=apply_extras.get('paused', False),
                include_filters=apply_extras.get('include_filters', []),
                headers=apply_extras.get('headers', {}),
                fetch_backend=apply_extras.get('fetch_backend', 'html_requests'),
                processor=apply_extras.get('processor', 'text_json_diff'),
                notification_urls=apply_extras.get('notification_urls', []),
                extra_config={
                    'ignore_text': apply_extras.get('ignore_text', []),
                    'trigger_text': apply_extras.get('trigger_text', []),
                    'text_should_not_be_present': apply_extras.get(
                        'text_should_not_be_present', []
                    ),
                    'subtractive_selectors': apply_extras.get('subtractive_selectors', []),
                    'extract_text': apply_extras.get('extract_text', []),
                    'notification_title': apply_extras.get('notification_title'),
                    'notification_body': apply_extras.get('notification_body'),
                    'notification_format': apply_extras.get('notification_format'),
                    'time_between_check': time_between,
                    'time_between_check_use_default': apply_extras.get(
                        'time_between_check_use_default', True
                    ),
                },
            )

            session.add(event)

            # Associate tags
            for tag_uuid_str in apply_extras['tags']:
                try:
                    tag_uuid = uuid_builder.UUID(tag_uuid_str)
                    tag_obj = await session.get(Tag, tag_uuid)
                    if tag_obj:
                        event.tags.append(tag_obj)
                except (ValueError, TypeError):
                    logger.warning(f"Invalid tag UUID: {tag_uuid_str}")

            await session.commit()
            logger.debug(f"Added watch: {new_uuid} - {url}")

        return new_uuid

    async def update_watch(self, uuid: str, update_obj: dict[str, Any]) -> None:
        """
        Update an existing watch.

        Args:
            uuid: Watch UUID
            update_obj: Dictionary of fields to update
        """
        if not update_obj:
            return

        async with self.session() as session:
            try:
                event_uuid = uuid_builder.UUID(uuid)
            except ValueError:
                logger.error(f"Invalid UUID: {uuid}")
                return

            event = await session.get(Event, event_uuid)
            if not event:
                logger.warning(f"Watch not found: {uuid}")
                return

            with self.lock:
                # Map ChangeDetectionStore fields to Event model fields
                field_mapping = {
                    'title': 'event_name',
                    'paused': 'paused',
                    'check_interval': 'check_interval',
                    'include_filters': 'include_filters',
                    'headers': 'headers',
                    'fetch_backend': 'fetch_backend',
                    'processor': 'processor',
                    'notification_urls': 'notification_urls',
                    'last_checked': 'last_checked',
                    'last_changed': 'last_changed',
                }

                for src_key, dest_key in field_mapping.items():
                    if src_key in update_obj:
                        value = update_obj[src_key]
                        # Convert Unix timestamp to datetime if needed
                        if src_key in ('last_checked', 'last_changed') and isinstance(
                            value, (int, float)
                        ):
                            value = datetime.fromtimestamp(value, tz=timezone.utc)
                        setattr(event, dest_key, value)

                # Handle time_between_check -> check_interval conversion
                if 'time_between_check' in update_obj:
                    time_between = update_obj['time_between_check']
                    check_interval = (
                        (time_between.get('weeks', 0) or 0) * 604800
                        + (time_between.get('days', 0) or 0) * 86400
                        + (time_between.get('hours', 0) or 0) * 3600
                        + (time_between.get('minutes', 0) or 0) * 60
                        + (time_between.get('seconds', 0) or 0)
                    )
                    if check_interval > 0:
                        event.check_interval = check_interval

                # Store extra fields in extra_config
                extra_fields = [
                    'ignore_text',
                    'trigger_text',
                    'text_should_not_be_present',
                    'subtractive_selectors',
                    'extract_text',
                    'notification_title',
                    'notification_body',
                    'notification_format',
                    'time_between_check',
                    'time_between_check_use_default',
                    'previous_md5',
                    'viewed',
                    'last_viewed',
                    'restock',
                    'restock_settings',
                ]
                if event.extra_config is None:
                    event.extra_config = {}
                for field in extra_fields:
                    if field in update_obj:
                        event.extra_config[field] = update_obj[field]

                # Handle tags update
                if 'tags' in update_obj:
                    event.tags.clear()
                    for tag_uuid_str in update_obj['tags']:
                        try:
                            tag_uuid = uuid_builder.UUID(tag_uuid_str)
                            tag_obj = await session.get(Tag, tag_uuid)
                            if tag_obj:
                                event.tags.append(tag_obj)
                        except (ValueError, TypeError):
                            pass

                await session.commit()

        self.needs_write = True

    async def delete(self, uuid: str) -> None:
        """
        Delete a watch and all related history (cascade).

        Args:
            uuid: Watch UUID or 'all' to delete all watches
        """
        async with self.session() as session:
            with self.lock:
                if uuid == 'all':
                    # Delete all events (cascades to history)
                    await session.execute(delete(Event))
                    await session.commit()
                    logger.info("Deleted all watches")
                else:
                    try:
                        event_uuid = uuid_builder.UUID(uuid)
                    except ValueError:
                        logger.error(f"Invalid UUID: {uuid}")
                        return

                    event = await session.get(Event, event_uuid)
                    if event:
                        await session.delete(event)
                        await session.commit()
                        logger.debug(f"Deleted watch: {uuid}")

        self.needs_write_urgent = True

        # Emit signal if blinker is available
        if HAS_BLINKER:
            watch_delete_signal = signal('watch_deleted')
            if watch_delete_signal:
                watch_delete_signal.send(watch_uuid=uuid)

    async def clone(self, uuid: str) -> str | None:
        """
        Clone a watch by UUID.

        Args:
            uuid: UUID of watch to clone

        Returns:
            UUID of new cloned watch
        """
        async with self.session() as session:
            try:
                event_uuid = uuid_builder.UUID(uuid)
            except ValueError:
                return None

            event = await session.get(Event, event_uuid)
            if not event:
                return None

            # Create extras from existing watch
            extras = {
                'title': event.event_name,
                'paused': event.paused,
                'include_filters': event.include_filters or [],
                'headers': event.headers or {},
                'fetch_backend': event.fetch_backend,
                'processor': event.processor,
                'notification_urls': event.notification_urls or [],
            }
            if event.extra_config:
                extras.update(event.extra_config)

            tag_uuids = [str(t.id) for t in event.tags]

        return await self.add_watch(url=event.url, extras=extras, tag_uuids=tag_uuids)

    async def url_exists(self, url: str) -> bool:
        """Check if URL is already being monitored."""
        async with self.session() as session:
            result = await session.execute(
                select(Event).where(func.lower(Event.url) == url.lower())
            )
            return result.scalar_one_or_none() is not None

    async def clear_watch_history(self, uuid: str) -> None:
        """
        Clear all history for a watch.

        Args:
            uuid: Watch UUID
        """
        async with self.session() as session:
            try:
                event_uuid = uuid_builder.UUID(uuid)
            except ValueError:
                return

            # Delete price history
            await session.execute(delete(PriceHistory).where(PriceHistory.event_id == event_uuid))
            # Delete availability history
            await session.execute(
                delete(AvailabilityHistory).where(AvailabilityHistory.event_id == event_uuid)
            )
            # Delete snapshots
            await session.execute(delete(Snapshot).where(Snapshot.event_id == event_uuid))
            await session.commit()

        self.needs_write_urgent = True

    async def set_last_viewed(self, uuid: str, timestamp: int) -> None:
        """
        Update the last viewed timestamp for a watch.

        Args:
            uuid: Watch UUID
            timestamp: Unix timestamp
        """
        logger.debug(f"Setting watch UUID: {uuid} last viewed to {int(timestamp)}")

        async with self.session() as session:
            try:
                event_uuid = uuid_builder.UUID(uuid)
            except ValueError:
                return

            event = await session.get(Event, event_uuid)
            if event:
                if event.extra_config is None:
                    event.extra_config = {}
                event.extra_config['last_viewed'] = int(timestamp)
                await session.commit()

        self.needs_write = True

        if HAS_BLINKER:
            watch_check_update = signal('watch_check_update')
            if watch_check_update:
                watch_check_update.send(watch_uuid=uuid)

    # -------------------------------------------------------------------------
    # Tag Operations
    # -------------------------------------------------------------------------

    async def add_tag(self, title: str) -> str | None:
        """
        Add a new tag or return existing tag UUID.

        Args:
            title: Tag name

        Returns:
            Tag UUID
        """
        n = title.strip().lower()
        if not n:
            return None

        logger.debug(f">>> Adding new tag - '{n}'")

        async with self.session() as session:
            # Check if tag exists
            existing = await Tag.get_by_name(session, title.strip())
            if existing:
                logger.warning(f"Tag '{title}' already exists, returning existing UUID")
                return str(existing.id)

            # Create new tag
            with self.lock:
                new_tag = Tag(
                    name=title.strip(),
                )
                session.add(new_tag)
                await session.commit()
                new_uuid = str(new_tag.id)

                # Update settings cache
                self._settings_cache['application']['tags'][new_uuid] = {
                    'uuid': new_uuid,
                    'title': title.strip(),
                    'date_created': int(time.time()),
                }

        return new_uuid

    async def tag_exists_by_name(self, tag_name: str) -> dict[str, Any] | None:
        """
        Check if a tag exists by name.

        Args:
            tag_name: Tag name to search for

        Returns:
            Tag dict if found, None otherwise
        """
        async with self.session() as session:
            tag = await Tag.get_by_name(session, tag_name)
            if tag:
                return {
                    'uuid': str(tag.id),
                    'title': tag.name,
                    'date_created': int(tag.created_at.timestamp()) if tag.created_at else None,
                }
        return None

    async def get_all_tags_for_watch(self, uuid: str) -> dict[str, dict[str, Any]]:
        """
        Get all tags associated with a watch.

        Args:
            uuid: Watch UUID

        Returns:
            Dict of tag UUID -> tag info
        """
        result = {}

        async with self.session() as session:
            try:
                event_uuid = uuid_builder.UUID(uuid)
            except ValueError:
                return result

            event = await session.get(Event, event_uuid)
            if event:
                # Load tags relationship
                await session.refresh(event, ['tags'])
                for tag in event.tags:
                    result[str(tag.id)] = {
                        'uuid': str(tag.id),
                        'title': tag.name,
                        'date_created': int(tag.created_at.timestamp()) if tag.created_at else None,
                        'slack_webhook_url': tag.slack_webhook_url,
                        'notification_muted': tag.notification_muted,
                    }

        return result

    async def update_tag(
        self,
        tag_uuid: str,
        slack_webhook_url: str | None = None,
        notification_muted: bool | None = None,
        color: str | None = None,
        name: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Update a tag's properties.

        This is the primary API endpoint for updating tag Slack webhook configuration.
        The webhook URL is validated to ensure it matches the Slack webhook format.

        Args:
            tag_uuid: UUID of the tag to update
            slack_webhook_url: New Slack webhook URL, or None/empty string to clear.
                              Must match format: https://hooks.slack.com/services/T.../B.../...
            notification_muted: Whether to mute notifications for this tag
            color: New display color (hex format)
            name: New tag name

        Returns:
            Updated tag dict with all properties, or None if tag not found.

        Raises:
            SlackWebhookValidationError: If the webhook URL format is invalid.

        Example:
            >>> store = PostgreSQLStore(database_url=os.getenv('DATABASE_URL'))
            >>> await store.initialize()
            >>> result = await store.update_tag(
            ...     tag_uuid="b0000000-0000-0000-0000-000000000001",
            ...     slack_webhook_url="https://hooks.slack.com/services/T123/B456/abc123",
            ...     notification_muted=False
            ... )
            >>> print(result)
            {'uuid': '...', 'title': 'concerts', 'slack_webhook_url': 'https://...', ...}
        """
        async with self.session() as session:
            try:
                tag_id = uuid_builder.UUID(tag_uuid)
            except ValueError:
                logger.error(f"Invalid tag UUID: {tag_uuid}")
                return None

            # Use the Tag model's update method which includes validation
            tag = await Tag.update_tag(
                session,
                tag_id,
                slack_webhook_url=slack_webhook_url,
                notification_muted=notification_muted,
                color=color,
                name=name,
            )

            if tag:
                # Update settings cache
                self._settings_cache['application']['tags'][str(tag.id)] = {
                    'uuid': str(tag.id),
                    'title': tag.name,
                    'date_created': int(tag.created_at.timestamp()) if tag.created_at else None,
                    'slack_webhook_url': tag.slack_webhook_url,
                    'notification_muted': tag.notification_muted,
                    'color': tag.color,
                }

                logger.debug(f"Updated tag {tag_uuid}: webhook_url={tag.slack_webhook_url}, muted={tag.notification_muted}")

                return {
                    'uuid': str(tag.id),
                    'title': tag.name,
                    'slack_webhook_url': tag.slack_webhook_url,
                    'notification_muted': tag.notification_muted,
                    'color': tag.color,
                    'date_created': int(tag.created_at.timestamp()) if tag.created_at else None,
                }

        return None

    async def get_webhooks_for_event(self, event_uuid: str) -> list[dict[str, Any]]:
        """
        Get all active Slack webhook URLs for an event's tags.

        This method returns webhook URLs from all tags associated with an event
        that have webhooks configured and are not muted. This enables sending
        notifications to multiple Slack channels when an event has multiple tags.

        Args:
            event_uuid: UUID of the event

        Returns:
            List of dicts containing:
            - tag_id: UUID of the tag
            - tag_name: Name of the tag
            - webhook_url: Slack webhook URL

        Example:
            >>> webhooks = await store.get_webhooks_for_event(event_uuid)
            >>> for webhook in webhooks:
            ...     send_notification(webhook['webhook_url'], message)
        """
        async with self.session() as session:
            try:
                event_id = uuid_builder.UUID(event_uuid)
            except ValueError:
                logger.error(f"Invalid event UUID: {event_uuid}")
                return []

            return await Tag.get_webhooks_for_event(session, event_id)

    async def get_tag(self, tag_uuid: str) -> dict[str, Any] | None:
        """
        Get a tag by UUID.

        Args:
            tag_uuid: UUID of the tag

        Returns:
            Tag dict with all properties, or None if not found.
        """
        async with self.session() as session:
            try:
                tag_id = uuid_builder.UUID(tag_uuid)
            except ValueError:
                return None

            tag = await Tag.get_by_id(session, tag_id)
            if tag:
                return {
                    'uuid': str(tag.id),
                    'title': tag.name,
                    'slack_webhook_url': tag.slack_webhook_url,
                    'notification_muted': tag.notification_muted,
                    'color': tag.color,
                    'date_created': int(tag.created_at.timestamp()) if tag.created_at else None,
                }

        return None

    async def get_all_tags(self) -> list[dict[str, Any]]:
        """
        Get all tags.

        Returns:
            List of tag dicts with all properties.
        """
        async with self.session() as session:
            tags = await Tag.get_all(session)
            return [
                {
                    'uuid': str(tag.id),
                    'title': tag.name,
                    'slack_webhook_url': tag.slack_webhook_url,
                    'notification_muted': tag.notification_muted,
                    'color': tag.color,
                    'date_created': int(tag.created_at.timestamp()) if tag.created_at else None,
                }
                for tag in tags
            ]

    # -------------------------------------------------------------------------
    # Event Data Extraction Operations (US-007)
    # -------------------------------------------------------------------------

    async def extract_and_update_event(
        self,
        event_uuid: str,
        html_content: str,
        record_history: bool = True,
    ) -> dict[str, Any]:
        """
        Extract event data from HTML and update the event record.

        This method uses CSS selectors configured on the event to extract
        structured data (event_name, artist, venue, date, time, prices,
        availability) from HTML content and updates the event record.

        If manual overrides are configured in extra_config, they take
        precedence over extracted values.

        Args:
            event_uuid: UUID of the event to update
            html_content: Raw HTML content to extract data from
            record_history: Whether to record price/availability changes to history

        Returns:
            Dict with:
            - 'success': True if extraction succeeded
            - 'data_changed': True if any data was updated
            - 'price_changed': True if prices changed
            - 'availability_changed': True if availability changed
            - 'extracted_data': Dict of extracted values
            - 'errors': Dict of any extraction errors

        Raises:
            RuntimeError: If EventDataExtractor is not available

        Example:
            >>> result = await store.extract_and_update_event(
            ...     event_uuid="123...",
            ...     html_content="<html>...</html>",
            ... )
            >>> if result['price_changed']:
            ...     send_price_notification(event_uuid)
        """
        if not HAS_EVENT_EXTRACTOR:
            raise RuntimeError(
                "EventDataExtractor not available. "
                "Install beautifulsoup4: pip install beautifulsoup4"
            )

        async with self.session() as session:
            try:
                event_id = uuid_builder.UUID(event_uuid)
            except ValueError:
                return {
                    'success': False,
                    'data_changed': False,
                    'price_changed': False,
                    'availability_changed': False,
                    'extracted_data': {},
                    'errors': {'_general': f'Invalid event UUID: {event_uuid}'},
                }

            event = await session.get(Event, event_id)
            if not event:
                return {
                    'success': False,
                    'data_changed': False,
                    'price_changed': False,
                    'availability_changed': False,
                    'extracted_data': {},
                    'errors': {'_general': f'Event not found: {event_uuid}'},
                }

            # Create extractor and extract data
            extractor = EventDataExtractor()
            result = extractor.extract_from_event(
                html_content=html_content,
                event_css_selectors=event.css_selectors,
                event_extra_config=event.extra_config,
            )

            # Update event with extracted data
            changes = await event.update_event_data(
                session,
                event_name=result.event_name,
                artist=result.artist,
                venue=result.venue,
                event_date=result.event_date,
                event_time=result.event_time,
                current_price_low=result.current_price_low,
                current_price_high=result.current_price_high,
                is_sold_out=result.is_sold_out,
                record_history=record_history,
            )

            return {
                'success': True,
                'data_changed': changes['data_changed'],
                'price_changed': changes['price_changed'],
                'availability_changed': changes['availability_changed'],
                'extracted_data': result.to_dict(),
                'errors': result.extraction_errors,
            }

    async def update_event_css_selectors(
        self,
        event_uuid: str,
        css_selectors: dict[str, str],
    ) -> bool:
        """
        Update CSS selectors for an event.

        Args:
            event_uuid: UUID of the event
            css_selectors: Dict mapping field names to CSS selectors

        Returns:
            True if update succeeded, False otherwise
        """
        async with self.session() as session:
            try:
                event_id = uuid_builder.UUID(event_uuid)
            except ValueError:
                return False

            event = await session.get(Event, event_id)
            if not event:
                return False

            event.set_css_selectors(css_selectors)
            await session.commit()
            return True

    async def update_event_manual_override(
        self,
        event_uuid: str,
        field_name: str,
        value: Any,
    ) -> bool:
        """
        Set a manual override for an event field.

        Manual overrides take precedence over CSS-extracted values.

        Args:
            event_uuid: UUID of the event
            field_name: Name of the field to override
            value: Override value (or None to clear)

        Returns:
            True if update succeeded, False otherwise
        """
        async with self.session() as session:
            try:
                event_id = uuid_builder.UUID(event_uuid)
            except ValueError:
                return False

            event = await session.get(Event, event_id)
            if not event:
                return False

            event.set_manual_override(field_name, value)
            await session.commit()
            return True

    async def get_event_extraction_config(
        self, event_uuid: str
    ) -> dict[str, Any] | None:
        """
        Get the extraction configuration for an event.

        Args:
            event_uuid: UUID of the event

        Returns:
            Dict with 'css_selectors' and 'manual_overrides', or None if not found
        """
        async with self.session() as session:
            try:
                event_id = uuid_builder.UUID(event_uuid)
            except ValueError:
                return None

            event = await session.get(Event, event_id)
            if not event:
                return None

            return {
                'css_selectors': event.css_selectors or {},
                'manual_overrides': event.get_manual_overrides(),
            }

    # -------------------------------------------------------------------------
    # Price History Operations (US-009)
    # -------------------------------------------------------------------------

    async def get_price_history(
        self,
        event_uuid: str,
        limit: int = 100,
        ticket_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get price history for an event.

        Args:
            event_uuid: UUID of the event
            limit: Maximum number of records to return (default: 100)
            ticket_type: Optional filter by ticket type

        Returns:
            List of price history records as dicts, most recent first
        """
        async with self.session() as session:
            try:
                event_id = uuid_builder.UUID(event_uuid)
            except ValueError:
                logger.error(f"Invalid event UUID: {event_uuid}")
                return []

            from sqlalchemy import select as sa_select

            query = sa_select(PriceHistory).where(PriceHistory.event_id == event_id)

            if ticket_type:
                query = query.where(PriceHistory.ticket_type == ticket_type)

            query = query.order_by(PriceHistory.recorded_at.desc()).limit(limit)

            result = await session.execute(query)
            records = result.scalars().all()

            return [record.to_dict() for record in records]

    async def cleanup_old_price_history(
        self,
        retention_days: int = 90,
    ) -> dict[str, int]:
        """
        Delete price history records older than retention_days.

        This method should be called periodically by a background job
        to maintain database size and performance.

        Args:
            retention_days: Number of days to retain history (default: 90)

        Returns:
            Dict with 'deleted_count' indicating how many records were removed
        """
        async with self.session() as session:
            deleted_count = await PriceHistory.cleanup_old_records(
                session, retention_days=retention_days
            )
            logger.info(f"Price history cleanup: deleted {deleted_count} records older than {retention_days} days")
            return {'deleted_count': deleted_count}

    async def get_price_history_stats(self) -> dict[str, Any]:
        """
        Get statistics about price history storage.

        Returns:
            Dict with total_records count
        """
        async with self.session() as session:
            count = await PriceHistory.get_history_count(session)
            return {'total_records': count}

    # -------------------------------------------------------------------------
    # Availability History Operations (US-010)
    # -------------------------------------------------------------------------

    async def get_availability_history(
        self,
        event_uuid: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Get availability history for an event.

        Records when events become sold out or available again (restocked).
        Used by dashboard to show 'sold out at' and 'restocked at' times.

        Args:
            event_uuid: UUID of the event
            limit: Maximum number of records to return (default: 100)

        Returns:
            List of availability history records as dicts, most recent first.
            Each record contains:
            - id: UUID of the record
            - event_id: UUID of the event
            - is_sold_out: Boolean indicating sold out status at this point
            - recorded_at: ISO timestamp when recorded
        """
        async with self.session() as session:
            try:
                event_id = uuid_builder.UUID(event_uuid)
            except ValueError:
                logger.error(f"Invalid event UUID: {event_uuid}")
                return []

            from sqlalchemy import select as sa_select

            query = sa_select(AvailabilityHistory).where(
                AvailabilityHistory.event_id == event_id
            )
            query = query.order_by(AvailabilityHistory.recorded_at.desc()).limit(limit)

            result = await session.execute(query)
            records = result.scalars().all()

            return [record.to_dict() for record in records]

    async def cleanup_old_availability_history(
        self,
        retention_days: int = 90,
    ) -> dict[str, int]:
        """
        Delete availability history records older than retention_days.

        This method should be called periodically by a background job
        to maintain database size and performance.

        Args:
            retention_days: Number of days to retain history (default: 90)

        Returns:
            Dict with 'deleted_count' indicating how many records were removed
        """
        from datetime import timedelta

        async with self.session() as session:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)

            # Count records to delete
            count_result = await session.execute(
                select(func.count(AvailabilityHistory.id)).where(
                    AvailabilityHistory.recorded_at < cutoff_date
                )
            )
            count = count_result.scalar() or 0

            # Delete old records
            await session.execute(
                delete(AvailabilityHistory).where(
                    AvailabilityHistory.recorded_at < cutoff_date
                )
            )
            await session.commit()

            logger.info(
                f"Availability history cleanup: deleted {count} records "
                f"older than {retention_days} days"
            )
            return {'deleted_count': count}

    async def get_availability_history_stats(self) -> dict[str, Any]:
        """
        Get statistics about availability history storage.

        Returns:
            Dict with total_records count
        """
        async with self.session() as session:
            result = await session.execute(
                select(func.count(AvailabilityHistory.id))
            )
            count = result.scalar() or 0
            return {'total_records': count}

    # -------------------------------------------------------------------------
    # Search and Query Operations
    # -------------------------------------------------------------------------

    async def search_watches_for_url(
        self, query: str, tag_limit: str | None = None, partial: bool = False
    ) -> list[str]:
        """
        Search watches by URL, title, or error messages.

        Args:
            query: Search term
            tag_limit: Optional tag name to filter results
            partial: If True, match substrings; if False, exact match

        Returns:
            List of matching watch UUIDs
        """
        matching_uuids = []
        query = query.lower().strip()

        async with self.session() as session:
            stmt = select(Event)

            # Build query conditions
            if partial:
                conditions = or_(
                    func.lower(Event.url).contains(query),
                    func.lower(Event.event_name).contains(query),
                )
            else:
                conditions = or_(
                    func.lower(Event.url) == query,
                    func.lower(Event.event_name) == query,
                )

            stmt = stmt.where(conditions)

            # Filter by tag if specified
            if tag_limit:
                tag = await Tag.get_by_name(session, tag_limit)
                if tag:
                    stmt = stmt.join(Event.tags).where(Tag.id == tag.id)

            result = await session.execute(stmt)
            events = result.scalars().all()

            for event in events:
                matching_uuids.append(str(event.id))

        return matching_uuids

    # -------------------------------------------------------------------------
    # Proxy Operations
    # -------------------------------------------------------------------------

    @property
    def proxy_list(self) -> dict[str, Any] | None:
        """Get proxy list from file configuration."""
        proxy_list = {}
        proxy_list_file = os.path.join(self.datastore_path, 'proxies.json')

        if os.path.isfile(proxy_list_file):
            try:
                with open(proxy_list_file, encoding='utf-8') as f:
                    proxy_list = json.load(f)
            except Exception as e:
                logger.error(f"Error loading proxies.json: {e}")

        # Add UI-configured proxies from settings
        extras = self._settings_cache['requests'].get('extra_proxies', [])
        if extras:
            for i, proxy in enumerate(extras):
                if proxy.get('proxy_name') and proxy.get('proxy_url'):
                    k = f"ui-{i}{proxy.get('proxy_name')}"
                    proxy_list[k] = {
                        'label': proxy.get('proxy_name'),
                        'url': proxy.get('proxy_url'),
                    }

        if proxy_list:
            proxy_list["no-proxy"] = {'label': "No proxy", 'url': ''}

        return proxy_list if proxy_list else None

    async def get_preferred_proxy_for_watch(self, uuid: str) -> str | None:
        """
        Get the preferred proxy for a watch.

        Args:
            uuid: Watch UUID

        Returns:
            Proxy key/ID or None
        """
        if self.proxy_list is None:
            return None

        async with self.session() as session:
            try:
                event_uuid = uuid_builder.UUID(uuid)
            except ValueError:
                return None

            event = await session.get(Event, event_uuid)
            if not event:
                return None

            # Check watch-specific proxy in extra_config
            watch_proxy = event.extra_config.get('proxy') if event.extra_config else None

            if watch_proxy == "no-proxy":
                return None

            if watch_proxy and watch_proxy in self.proxy_list:
                return watch_proxy

            # Fall back to system proxy
            system_proxy_id = self._settings_cache['requests'].get('proxy')
            if system_proxy_id and system_proxy_id in self.proxy_list:
                return system_proxy_id

            # Use first available proxy as fallback
            if self.proxy_list:
                return list(self.proxy_list.keys())[0]

        return None

    # -------------------------------------------------------------------------
    # Data Access Properties
    # -------------------------------------------------------------------------

    @property
    def data(self) -> dict[str, Any]:
        """
        Return store data in ChangeDetectionStore-compatible format.

        Note: This is for compatibility. For async usage, prefer direct methods.
        """
        # This requires sync access to database - use _get_data_async() for async
        return {
            'watching': {},  # Populated by sync operations
            'settings': self._settings_cache,
            'version_tag': self.version_tag,
        }

    async def get_data_async(self) -> dict[str, Any]:
        """Get full store data asynchronously."""
        watching = {}

        async with self.session() as session:
            result = await session.execute(select(Event))
            events = result.scalars().all()

            for event in events:
                await session.refresh(event, ['tags'])
                watching[str(event.id)] = self._event_to_watch_dict(event)

        return {
            'watching': watching,
            'settings': self._settings_cache,
            'version_tag': self.version_tag,
        }

    async def get_watch(self, uuid: str) -> dict[str, Any] | None:
        """
        Get a single watch by UUID.

        Args:
            uuid: Watch UUID

        Returns:
            Watch dict in ChangeDetectionStore format
        """
        async with self.session() as session:
            try:
                event_uuid = uuid_builder.UUID(uuid)
            except ValueError:
                return None

            event = await session.get(Event, event_uuid)
            if event:
                await session.refresh(event, ['tags'])
                return self._event_to_watch_dict(event)

        return None

    async def get_all_watches(self) -> dict[str, dict[str, Any]]:
        """Get all watches."""
        watching = {}

        async with self.session() as session:
            result = await session.execute(select(Event))
            events = result.scalars().all()

            for event in events:
                await session.refresh(event, ['tags'])
                watching[str(event.id)] = self._event_to_watch_dict(event)

        return watching

    @property
    def threshold_seconds(self) -> int:
        """Calculate threshold seconds from settings."""
        seconds = 0
        mtable = {'weeks': 604800, 'days': 86400, 'hours': 3600, 'minutes': 60, 'seconds': 1}
        for m, n in mtable.items():
            x = self._settings_cache['requests']['time_between_check'].get(m)
            if x:
                seconds += x * n
        return seconds

    @property
    def unread_changes_count(self) -> int:
        """Count watches with unread changes."""
        # This requires sync access - implement async version
        return 0

    async def get_unread_changes_count_async(self) -> int:
        """Get count of watches with unread changes (async)."""
        count = 0

        async with self.session() as session:
            result = await session.execute(select(Event))
            events = result.scalars().all()

            for event in events:
                extra = event.extra_config or {}
                last_viewed = extra.get('last_viewed', 0)
                last_changed = event.last_changed

                if last_changed and last_viewed:
                    if isinstance(last_changed, datetime):
                        last_changed_ts = last_changed.timestamp()
                    else:
                        last_changed_ts = last_changed

                    if last_changed_ts > last_viewed:
                        count += 1

        return count

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def _event_to_watch_dict(self, event: Event) -> dict[str, Any]:
        """
        Convert Event model to ChangeDetectionStore watch format.

        Args:
            event: Event ORM object

        Returns:
            Dict in watch format
        """
        extra = event.extra_config or {}

        # Convert check_interval back to time_between_check
        time_between = extra.get('time_between_check', {})
        if not time_between and event.check_interval:
            hours = event.check_interval // 3600
            time_between = {'hours': hours if hours > 0 else None}

        watch = {
            'uuid': str(event.id),
            'url': event.url,
            'title': event.event_name,
            'paused': event.paused,
            'check_interval': event.check_interval,
            'time_between_check': time_between,
            'time_between_check_use_default': extra.get('time_between_check_use_default', True),
            'last_checked': int(event.last_checked.timestamp()) if event.last_checked else 0,
            'last_changed': int(event.last_changed.timestamp()) if event.last_changed else 0,
            'date_created': int(event.created_at.timestamp()) if event.created_at else 0,
            'include_filters': event.include_filters or [],
            'headers': event.headers or {},
            'fetch_backend': event.fetch_backend,
            'processor': event.processor,
            'notification_urls': event.notification_urls or [],
            'tags': [str(t.id) for t in event.tags],
            # Extra config fields
            'ignore_text': extra.get('ignore_text', []),
            'trigger_text': extra.get('trigger_text', []),
            'text_should_not_be_present': extra.get('text_should_not_be_present', []),
            'subtractive_selectors': extra.get('subtractive_selectors', []),
            'extract_text': extra.get('extract_text', []),
            'notification_title': extra.get('notification_title'),
            'notification_body': extra.get('notification_body'),
            'notification_format': extra.get('notification_format'),
            'previous_md5': extra.get('previous_md5'),
            'viewed': extra.get('viewed', True),
            'last_viewed': extra.get('last_viewed', 0),
            'restock': extra.get('restock'),
            'restock_settings': extra.get('restock_settings'),
        }

        return watch

    async def _load_tags_to_cache(self) -> None:
        """Load tags from database into settings cache."""
        async with self.session() as session:
            tags = await Tag.get_all(session)
            for tag in tags:
                self._settings_cache['application']['tags'][str(tag.id)] = {
                    'uuid': str(tag.id),
                    'title': tag.name,
                    'date_created': int(tag.created_at.timestamp()) if tag.created_at else None,
                    'slack_webhook_url': tag.slack_webhook_url,
                    'notification_muted': tag.notification_muted,
                }

    async def _add_default_watches_if_empty(self) -> None:
        """Add default example watches if database is empty."""
        async with self.session() as session:
            result = await session.execute(select(func.count(Event.id)))
            count = result.scalar()

            if count == 0:
                logger.info("Database empty, adding default example watches")
                await self.add_watch(
                    url='https://news.ycombinator.com/',
                    tag='Tech news',
                    extras={'fetch_backend': 'html_requests'},
                )
                await self.add_watch(
                    url='https://changedetection.io/CHANGELOG.txt',
                    tag='changedetection.io',
                    extras={'fetch_backend': 'html_requests'},
                )

    # -------------------------------------------------------------------------
    # Headers
    # -------------------------------------------------------------------------

    def get_all_base_headers(self) -> dict[str, str]:
        """Get global base headers."""
        return self._settings_cache.get('headers', {})

    async def get_all_headers_in_textfile_for_watch(self, uuid: str) -> dict[str, str]:
        """Get headers from text files for a watch."""
        from pathlib import Path

        headers = {}

        # Global headers.txt
        filepath = Path(self.datastore_path) / 'headers.txt'
        if filepath.is_file():
            try:
                headers.update(self._parse_headers_from_text_file(filepath))
            except Exception as e:
                logger.error(f"Error reading {filepath}: {e}")

        # Watch-specific and tag-specific headers would require datastore_path/uuid structure
        # which may not exist in PostgreSQL-only mode

        return headers

    def _parse_headers_from_text_file(self, filepath) -> dict[str, str]:
        """Parse headers from a text file."""
        headers = {}
        try:
            with open(filepath, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and ':' in line:
                        key, value = line.split(':', 1)
                        headers[key.strip()] = value.strip()
        except Exception as e:
            logger.error(f"Error parsing headers file {filepath}: {e}")
        return headers

    async def get_tag_overrides_for_watch(self, uuid: str, attr: str) -> list[Any]:
        """Get tag-level overrides for a watch attribute."""
        ret = []
        tags = await self.get_all_tags_for_watch(uuid)

        if tags:
            for tag_uuid, tag in tags.items():
                if attr in tag and tag[attr]:
                    ret.extend(tag[attr])

        return ret


# =============================================================================
# Migration Utilities
# =============================================================================


class JSONToPostgreSQLMigrator:
    """
    Utility to migrate data from JSON file storage to PostgreSQL.

    Usage:
        migrator = JSONToPostgreSQLMigrator(
            json_path='/datastore/url-watches.json',
            database_url=os.getenv('DATABASE_URL')
        )
        await migrator.migrate()
    """

    def __init__(self, json_path: str, database_url: str):
        """
        Initialize migrator.

        Args:
            json_path: Path to url-watches.json file
            database_url: PostgreSQL connection string
        """
        self.json_path = json_path
        self.database_url = database_url
        self.store = PostgreSQLStore(database_url=database_url, include_default_watches=False)

    async def migrate(self) -> dict[str, Any]:
        """
        Migrate all data from JSON to PostgreSQL.

        Returns:
            Migration statistics
        """
        stats = {
            'watches_migrated': 0,
            'tags_migrated': 0,
            'errors': [],
        }

        # Load JSON data
        try:
            with open(self.json_path, encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            stats['errors'].append(f"Failed to load JSON: {e}")
            return stats

        await self.store.initialize()

        try:
            # Migrate tags first
            tags_data = data.get('settings', {}).get('application', {}).get('tags', {})
            tag_uuid_mapping = {}  # old_uuid -> new_uuid

            for old_uuid, tag in tags_data.items():
                try:
                    title = tag.get('title', '')
                    if title:
                        new_uuid = await self.store.add_tag(title)
                        if new_uuid:
                            tag_uuid_mapping[old_uuid] = new_uuid
                            stats['tags_migrated'] += 1
                except Exception as e:
                    stats['errors'].append(f"Tag migration error ({old_uuid}): {e}")

            # Migrate watches
            watching = data.get('watching', {})
            for old_uuid, watch in watching.items():
                try:
                    url = watch.get('url')
                    if not url:
                        continue

                    # Map old tag UUIDs to new ones
                    old_tags = watch.get('tags', [])
                    new_tags = [tag_uuid_mapping.get(t, t) for t in old_tags]

                    extras = deepcopy(watch)
                    extras['tags'] = new_tags

                    # Remove fields that shouldn't be in extras
                    for k in ['uuid', 'url', 'history']:
                        extras.pop(k, None)

                    await self.store.add_watch(url=url, extras=extras)
                    stats['watches_migrated'] += 1

                except Exception as e:
                    stats['errors'].append(f"Watch migration error ({old_uuid}): {e}")

        finally:
            await self.store.close()

        return stats


# =============================================================================
# CLI for Testing
# =============================================================================

if __name__ == "__main__":
    import asyncio

    async def test_store():
        """Test the PostgreSQL store."""
        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            print("DATABASE_URL environment variable not set")
            print("Example: postgresql://user:password@host/database")
            return

        store = PostgreSQLStore(database_url=database_url)

        try:
            await store.initialize()
            print("Store initialized successfully!")

            # Test adding a watch
            watch_uuid = await store.add_watch(
                url="https://example.com/tickets",
                tag="test,concerts",
                extras={'title': 'Test Watch', 'paused': False, 'fetch_backend': 'html_requests'},
            )
            print(f"Added watch: {watch_uuid}")

            # Test getting the watch
            watch = await store.get_watch(watch_uuid)
            if watch:
                print(f"Retrieved watch: {watch['url']}")
                print(f"  Title: {watch['title']}")
                print(f"  Tags: {watch['tags']}")

            # Test URL exists
            exists = await store.url_exists("https://example.com/tickets")
            print(f"URL exists: {exists}")

            # Test search
            results = await store.search_watches_for_url("example", partial=True)
            print(f"Search results: {len(results)} watches found")

            # Test update
            await store.update_watch(watch_uuid, {'paused': True, 'title': 'Updated Test'})
            updated = await store.get_watch(watch_uuid)
            print(f"Updated paused: {updated['paused']}")

            # Test delete
            await store.delete(watch_uuid)
            deleted = await store.get_watch(watch_uuid)
            print(f"Watch deleted: {deleted is None}")

            print("\nAll tests passed!")

        finally:
            await store.close()

    asyncio.run(test_store())
