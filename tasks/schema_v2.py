"""
PostgreSQL Schema V2 for ATC Page Monitor

This module defines the comprehensive database schema for the ATC Page Monitor
ticketing intelligence platform, including:
- Users with role-based access (admin/viewer)
- Tags with Slack webhook routing
- Events with full ticketing data extraction fields
- Price and availability history tracking
- Notification logging for debugging and metrics

Schema Version: 2

Usage:
    from tasks.schema_v2 import apply_schema_v2, SCHEMA_VERSION

    # Apply schema (creates tables if not exist, migrates if needed)
    await apply_schema_v2(connection_pool)
"""

import os
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict, field
from enum import Enum

# Schema version for migration tracking
SCHEMA_VERSION = 2


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
# SQL Schema Definitions
# =============================================================================

CREATE_SCHEMA_VERSION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    description TEXT
);
"""

# -----------------------------------------------------------------------------
# Users Table
# -----------------------------------------------------------------------------
CREATE_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'viewer' CHECK (role IN ('admin', 'viewer')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_login TIMESTAMP WITH TIME ZONE,
    is_active BOOLEAN DEFAULT TRUE,

    CONSTRAINT users_email_not_empty CHECK (email <> ''),
    CONSTRAINT users_password_hash_not_empty CHECK (password_hash <> '')
);
"""

CREATE_USERS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);",
    "CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);",
    "CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active);",
]

# -----------------------------------------------------------------------------
# Tags Table
# -----------------------------------------------------------------------------
CREATE_TAGS_TABLE = """
CREATE TABLE IF NOT EXISTS tags (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    slack_webhook_url TEXT,
    notification_muted BOOLEAN DEFAULT FALSE,
    color TEXT DEFAULT '#3B82F6',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,

    CONSTRAINT tags_name_not_empty CHECK (name <> '')
);
"""

CREATE_TAGS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name);",
    "CREATE INDEX IF NOT EXISTS idx_tags_created_by ON tags(created_by);",
    "CREATE INDEX IF NOT EXISTS idx_tags_notification_muted ON tags(notification_muted);",
]

# -----------------------------------------------------------------------------
# Events Table
# -----------------------------------------------------------------------------
CREATE_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Core identification
    url TEXT NOT NULL,

    -- Event metadata (extracted or manual)
    event_name TEXT,
    artist TEXT,
    venue TEXT,
    event_date DATE,
    event_time TIME,

    -- Pricing data
    current_price_low DECIMAL(10, 2),
    current_price_high DECIMAL(10, 2),

    -- Availability
    is_sold_out BOOLEAN DEFAULT FALSE,

    -- Ticket type tracking
    ticket_types JSONB DEFAULT '[]'::jsonb,
    track_specific_types BOOLEAN DEFAULT FALSE,

    -- Monitoring configuration
    check_interval INTEGER DEFAULT 3600,
    paused BOOLEAN DEFAULT FALSE,

    -- CSS selectors for extraction
    include_filters JSONB DEFAULT '[]'::jsonb,
    css_selectors JSONB DEFAULT '{}'::jsonb,

    -- Request configuration
    headers JSONB DEFAULT '{}'::jsonb,
    fetch_backend TEXT DEFAULT 'playwright',
    processor TEXT DEFAULT 'text_json_diff',

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_checked TIMESTAMP WITH TIME ZONE,
    last_changed TIMESTAMP WITH TIME ZONE,

    -- Extra configuration (extensible)
    extra_config JSONB DEFAULT '{}'::jsonb,

    -- Notification URLs (legacy support)
    notification_urls JSONB DEFAULT '[]'::jsonb,

    CONSTRAINT events_url_not_empty CHECK (url <> '')
);
"""

CREATE_EVENTS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_events_url ON events(url);",
    "CREATE INDEX IF NOT EXISTS idx_events_event_name ON events(event_name);",
    "CREATE INDEX IF NOT EXISTS idx_events_artist ON events(artist);",
    "CREATE INDEX IF NOT EXISTS idx_events_venue ON events(venue);",
    "CREATE INDEX IF NOT EXISTS idx_events_event_date ON events(event_date);",
    "CREATE INDEX IF NOT EXISTS idx_events_is_sold_out ON events(is_sold_out);",
    "CREATE INDEX IF NOT EXISTS idx_events_paused ON events(paused);",
    "CREATE INDEX IF NOT EXISTS idx_events_last_checked ON events(last_checked);",
    "CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at);",
]

# -----------------------------------------------------------------------------
# Event-Tags Junction Table (Many-to-Many)
# -----------------------------------------------------------------------------
CREATE_EVENT_TAGS_TABLE = """
CREATE TABLE IF NOT EXISTS event_tags (
    event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    tag_id UUID NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    assigned_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    assigned_by UUID REFERENCES users(id) ON DELETE SET NULL,

    PRIMARY KEY (event_id, tag_id)
);
"""

CREATE_EVENT_TAGS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_event_tags_event_id ON event_tags(event_id);",
    "CREATE INDEX IF NOT EXISTS idx_event_tags_tag_id ON event_tags(tag_id);",
]

# -----------------------------------------------------------------------------
# Price History Table
# -----------------------------------------------------------------------------
CREATE_PRICE_HISTORY_TABLE = """
CREATE TABLE IF NOT EXISTS price_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    price_low DECIMAL(10, 2),
    price_high DECIMAL(10, 2),
    ticket_type TEXT,
    recorded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
"""

CREATE_PRICE_HISTORY_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_price_history_event_id ON price_history(event_id);",
    "CREATE INDEX IF NOT EXISTS idx_price_history_recorded_at ON price_history(recorded_at);",
    "CREATE INDEX IF NOT EXISTS idx_price_history_event_recorded ON price_history(event_id, recorded_at DESC);",
]

# -----------------------------------------------------------------------------
# Availability History Table
# -----------------------------------------------------------------------------
CREATE_AVAILABILITY_HISTORY_TABLE = """
CREATE TABLE IF NOT EXISTS availability_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    is_sold_out BOOLEAN NOT NULL,
    recorded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
"""

CREATE_AVAILABILITY_HISTORY_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_availability_history_event_id ON availability_history(event_id);",
    "CREATE INDEX IF NOT EXISTS idx_availability_history_recorded_at ON availability_history(recorded_at);",
    "CREATE INDEX IF NOT EXISTS idx_availability_history_event_recorded ON availability_history(event_id, recorded_at DESC);",
]

# -----------------------------------------------------------------------------
# Notification Log Table
# -----------------------------------------------------------------------------
CREATE_NOTIFICATION_LOG_TABLE = """
CREATE TABLE IF NOT EXISTS notification_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID REFERENCES events(id) ON DELETE SET NULL,
    tag_id UUID REFERENCES tags(id) ON DELETE SET NULL,

    notification_type TEXT NOT NULL CHECK (notification_type IN ('restock', 'price_change', 'sold_out', 'new_event', 'error')),
    webhook_url TEXT,

    -- Request/Response details
    payload JSONB,
    response_status INTEGER,
    response_body TEXT,

    -- Status
    success BOOLEAN DEFAULT FALSE,
    error_message TEXT,

    -- Timestamps
    sent_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Additional context
    metadata JSONB DEFAULT '{}'::jsonb
);
"""

CREATE_NOTIFICATION_LOG_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_notification_log_event_id ON notification_log(event_id);",
    "CREATE INDEX IF NOT EXISTS idx_notification_log_tag_id ON notification_log(tag_id);",
    "CREATE INDEX IF NOT EXISTS idx_notification_log_notification_type ON notification_log(notification_type);",
    "CREATE INDEX IF NOT EXISTS idx_notification_log_sent_at ON notification_log(sent_at);",
    "CREATE INDEX IF NOT EXISTS idx_notification_log_success ON notification_log(success);",
]

# -----------------------------------------------------------------------------
# Legacy Snapshots Table (for backward compatibility with MVP)
# -----------------------------------------------------------------------------
CREATE_SNAPSHOTS_TABLE = """
CREATE TABLE IF NOT EXISTS snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    content_hash TEXT NOT NULL,
    captured_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    extracted_prices JSONB,
    extracted_availability TEXT,
    content_text TEXT,
    content_url TEXT
);
"""

CREATE_SNAPSHOTS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_snapshots_event_id ON snapshots(event_id);",
    "CREATE INDEX IF NOT EXISTS idx_snapshots_captured_at ON snapshots(captured_at);",
    "CREATE INDEX IF NOT EXISTS idx_snapshots_content_hash ON snapshots(content_hash);",
]


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class UserRecord:
    """Database record for a user"""
    id: str
    email: str
    password_hash: str
    role: str = "viewer"
    created_at: Optional[datetime] = None
    last_login: Optional[datetime] = None
    is_active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        for key in ['created_at', 'last_login']:
            if result[key] is not None:
                result[key] = result[key].isoformat()
        return result


@dataclass
class TagRecord:
    """Database record for a tag"""
    id: str
    name: str
    slack_webhook_url: Optional[str] = None
    notification_muted: bool = False
    color: str = "#3B82F6"
    created_at: Optional[datetime] = None
    created_by: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        if result['created_at'] is not None:
            result['created_at'] = result['created_at'].isoformat()
        return result


@dataclass
class EventRecord:
    """Database record for an event"""
    id: str
    url: str
    event_name: Optional[str] = None
    artist: Optional[str] = None
    venue: Optional[str] = None
    event_date: Optional[str] = None  # DATE as string
    event_time: Optional[str] = None  # TIME as string
    current_price_low: Optional[float] = None
    current_price_high: Optional[float] = None
    is_sold_out: bool = False
    ticket_types: Optional[List[str]] = None
    track_specific_types: bool = False
    check_interval: int = 3600
    paused: bool = False
    include_filters: Optional[List[str]] = None
    css_selectors: Optional[Dict[str, str]] = None
    headers: Optional[Dict[str, str]] = None
    fetch_backend: str = "playwright"
    processor: str = "text_json_diff"
    created_at: Optional[datetime] = None
    last_checked: Optional[datetime] = None
    last_changed: Optional[datetime] = None
    extra_config: Optional[Dict[str, Any]] = None
    notification_urls: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        for key in ['created_at', 'last_checked', 'last_changed']:
            if result[key] is not None:
                result[key] = result[key].isoformat()
        return result


@dataclass
class PriceHistoryRecord:
    """Database record for price history"""
    id: str
    event_id: str
    price_low: Optional[float] = None
    price_high: Optional[float] = None
    ticket_type: Optional[str] = None
    recorded_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        if result['recorded_at'] is not None:
            result['recorded_at'] = result['recorded_at'].isoformat()
        return result


@dataclass
class AvailabilityHistoryRecord:
    """Database record for availability history"""
    id: str
    event_id: str
    is_sold_out: bool
    recorded_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        if result['recorded_at'] is not None:
            result['recorded_at'] = result['recorded_at'].isoformat()
        return result


@dataclass
class NotificationLogRecord:
    """Database record for notification log"""
    id: str
    notification_type: str
    event_id: Optional[str] = None
    tag_id: Optional[str] = None
    webhook_url: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None
    response_status: Optional[int] = None
    response_body: Optional[str] = None
    success: bool = False
    error_message: Optional[str] = None
    sent_at: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        if result['sent_at'] is not None:
            result['sent_at'] = result['sent_at'].isoformat()
        return result


# =============================================================================
# Schema Application Functions
# =============================================================================

async def apply_schema_v2(pool) -> None:
    """
    Apply schema version 2 to the database.

    Creates all tables and indexes if they don't exist.
    Handles migration from v1 schema if needed.

    Args:
        pool: asyncpg connection pool
    """
    async with pool.acquire() as conn:
        # Create schema version table
        await conn.execute(CREATE_SCHEMA_VERSION_TABLE)

        # Check current schema version
        current_version = await conn.fetchval(
            "SELECT COALESCE(MAX(version), 0) FROM schema_version"
        )

        if current_version >= SCHEMA_VERSION:
            return  # Already at or past this version

        # Begin transaction for schema changes
        async with conn.transaction():
            # Create tables in dependency order
            await conn.execute(CREATE_USERS_TABLE)
            await conn.execute(CREATE_TAGS_TABLE)
            await conn.execute(CREATE_EVENTS_TABLE)
            await conn.execute(CREATE_EVENT_TAGS_TABLE)
            await conn.execute(CREATE_PRICE_HISTORY_TABLE)
            await conn.execute(CREATE_AVAILABILITY_HISTORY_TABLE)
            await conn.execute(CREATE_NOTIFICATION_LOG_TABLE)
            await conn.execute(CREATE_SNAPSHOTS_TABLE)

            # Create all indexes
            all_indexes = (
                CREATE_USERS_INDEXES +
                CREATE_TAGS_INDEXES +
                CREATE_EVENTS_INDEXES +
                CREATE_EVENT_TAGS_INDEXES +
                CREATE_PRICE_HISTORY_INDEXES +
                CREATE_AVAILABILITY_HISTORY_INDEXES +
                CREATE_NOTIFICATION_LOG_INDEXES +
                CREATE_SNAPSHOTS_INDEXES
            )

            for index_sql in all_indexes:
                await conn.execute(index_sql)

            # Handle migration from v1 if needed
            if current_version == 1:
                await _migrate_v1_to_v2(conn)

            # Record schema version
            await conn.execute(
                """
                INSERT INTO schema_version (version, description)
                VALUES ($1, $2)
                ON CONFLICT (version) DO NOTHING
                """,
                SCHEMA_VERSION,
                "ATC Page Monitor schema with users, tags, events, price_history, availability_history, notification_log"
            )


async def _migrate_v1_to_v2(conn) -> None:
    """
    Migrate data from v1 schema (watches, snapshots) to v2 schema (events).

    This preserves existing watch data by copying it to the events table.
    """
    # Check if watches table exists (v1 schema)
    watches_exists = await conn.fetchval("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_name = 'watches'
        )
    """)

    if not watches_exists:
        return

    # Migrate watches to events
    await conn.execute("""
        INSERT INTO events (
            id, url, event_name, check_interval, paused,
            include_filters, headers, fetch_backend, processor,
            created_at, last_checked, last_changed, extra_config,
            notification_urls
        )
        SELECT
            id, url, title, check_interval, paused,
            include_filters, headers, fetch_backend, processor,
            created_at, last_checked, last_changed, extra_config,
            notification_urls
        FROM watches
        ON CONFLICT (id) DO NOTHING
    """)

    # Update snapshots foreign key if needed (rename watch_id to event_id)
    # Note: The snapshots table in v2 uses event_id instead of watch_id
    # We need to handle this carefully

    # Check if snapshots table has watch_id column
    has_watch_id = await conn.fetchval("""
        SELECT EXISTS (
            SELECT FROM information_schema.columns
            WHERE table_name = 'snapshots' AND column_name = 'watch_id'
        )
    """)

    if has_watch_id:
        # Add event_id column if not exists
        await conn.execute("""
            ALTER TABLE snapshots
            ADD COLUMN IF NOT EXISTS event_id UUID REFERENCES events(id) ON DELETE CASCADE
        """)

        # Copy watch_id to event_id
        await conn.execute("""
            UPDATE snapshots SET event_id = watch_id WHERE event_id IS NULL
        """)


def apply_schema_v2_sync(conn) -> None:
    """
    Apply schema version 2 to the database (synchronous version).

    Args:
        conn: psycopg2 connection
    """
    with conn.cursor() as cur:
        # Create schema version table
        cur.execute(CREATE_SCHEMA_VERSION_TABLE)

        # Check current schema version
        cur.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version")
        current_version = cur.fetchone()[0]

        if current_version >= SCHEMA_VERSION:
            return

        # Create tables in dependency order
        cur.execute(CREATE_USERS_TABLE)
        cur.execute(CREATE_TAGS_TABLE)
        cur.execute(CREATE_EVENTS_TABLE)
        cur.execute(CREATE_EVENT_TAGS_TABLE)
        cur.execute(CREATE_PRICE_HISTORY_TABLE)
        cur.execute(CREATE_AVAILABILITY_HISTORY_TABLE)
        cur.execute(CREATE_NOTIFICATION_LOG_TABLE)
        cur.execute(CREATE_SNAPSHOTS_TABLE)

        # Create all indexes
        all_indexes = (
            CREATE_USERS_INDEXES +
            CREATE_TAGS_INDEXES +
            CREATE_EVENTS_INDEXES +
            CREATE_EVENT_TAGS_INDEXES +
            CREATE_PRICE_HISTORY_INDEXES +
            CREATE_AVAILABILITY_HISTORY_INDEXES +
            CREATE_NOTIFICATION_LOG_INDEXES +
            CREATE_SNAPSHOTS_INDEXES
        )

        for index_sql in all_indexes:
            cur.execute(index_sql)

        # Record schema version
        cur.execute(
            """
            INSERT INTO schema_version (version, description)
            VALUES (%s, %s)
            ON CONFLICT (version) DO NOTHING
            """,
            (SCHEMA_VERSION, "ATC Page Monitor schema with users, tags, events, price_history, availability_history, notification_log")
        )

        conn.commit()


# =============================================================================
# Sample Data for Testing
# =============================================================================

SAMPLE_DATA_SQL = """
-- Sample admin user (password: 'admin123' - bcrypt hash)
INSERT INTO users (id, email, password_hash, role, created_at)
VALUES (
    'a0000000-0000-0000-0000-000000000001',
    'admin@example.com',
    '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.XsZ.OFYfL.lC4W',
    'admin',
    NOW()
) ON CONFLICT (id) DO NOTHING;

-- Sample viewer user (password: 'viewer123' - bcrypt hash)
INSERT INTO users (id, email, password_hash, role, created_at)
VALUES (
    'a0000000-0000-0000-0000-000000000002',
    'viewer@example.com',
    '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.XsZ.OFYfL.lC4W',
    'viewer',
    NOW()
) ON CONFLICT (id) DO NOTHING;

-- Sample tags
INSERT INTO tags (id, name, slack_webhook_url, color, created_by)
VALUES
    ('b0000000-0000-0000-0000-000000000001', 'concerts', NULL, '#EF4444', 'a0000000-0000-0000-0000-000000000001'),
    ('b0000000-0000-0000-0000-000000000002', 'comedy', NULL, '#F59E0B', 'a0000000-0000-0000-0000-000000000001'),
    ('b0000000-0000-0000-0000-000000000003', 'sports', NULL, '#10B981', 'a0000000-0000-0000-0000-000000000001')
ON CONFLICT (id) DO NOTHING;

-- Sample event
INSERT INTO events (
    id, url, event_name, artist, venue, event_date, event_time,
    current_price_low, current_price_high, is_sold_out,
    check_interval, paused
) VALUES (
    'c0000000-0000-0000-0000-000000000001',
    'https://metrochicago.com/event/sample-concert',
    'Sample Concert',
    'Sample Artist',
    'Metro Chicago',
    '2026-03-15',
    '20:00',
    35.00,
    75.00,
    FALSE,
    1800,
    FALSE
) ON CONFLICT (id) DO NOTHING;

-- Link event to tag
INSERT INTO event_tags (event_id, tag_id, assigned_by)
VALUES (
    'c0000000-0000-0000-0000-000000000001',
    'b0000000-0000-0000-0000-000000000001',
    'a0000000-0000-0000-0000-000000000001'
) ON CONFLICT (event_id, tag_id) DO NOTHING;

-- Sample price history
INSERT INTO price_history (id, event_id, price_low, price_high, ticket_type, recorded_at)
VALUES
    ('d0000000-0000-0000-0000-000000000001', 'c0000000-0000-0000-0000-000000000001', 30.00, 70.00, 'GA', NOW() - INTERVAL '2 days'),
    ('d0000000-0000-0000-0000-000000000002', 'c0000000-0000-0000-0000-000000000001', 32.00, 72.00, 'GA', NOW() - INTERVAL '1 day'),
    ('d0000000-0000-0000-0000-000000000003', 'c0000000-0000-0000-0000-000000000001', 35.00, 75.00, 'GA', NOW())
ON CONFLICT (id) DO NOTHING;

-- Sample availability history
INSERT INTO availability_history (id, event_id, is_sold_out, recorded_at)
VALUES
    ('e0000000-0000-0000-0000-000000000001', 'c0000000-0000-0000-0000-000000000001', FALSE, NOW() - INTERVAL '2 days'),
    ('e0000000-0000-0000-0000-000000000002', 'c0000000-0000-0000-0000-000000000001', TRUE, NOW() - INTERVAL '1 day'),
    ('e0000000-0000-0000-0000-000000000003', 'c0000000-0000-0000-0000-000000000001', FALSE, NOW())
ON CONFLICT (id) DO NOTHING;

-- Sample notification log
INSERT INTO notification_log (
    id, event_id, tag_id, notification_type, webhook_url,
    payload, response_status, success, sent_at
) VALUES (
    'f0000000-0000-0000-0000-000000000001',
    'c0000000-0000-0000-0000-000000000001',
    'b0000000-0000-0000-0000-000000000001',
    'restock',
    'https://hooks.slack.com/services/SAMPLE/WEBHOOK/URL',
    '{"text": "RESTOCK ALERT: Sample Concert"}',
    200,
    TRUE,
    NOW()
) ON CONFLICT (id) DO NOTHING;
"""


async def insert_sample_data(pool) -> None:
    """Insert sample data for testing."""
    async with pool.acquire() as conn:
        await conn.execute(SAMPLE_DATA_SQL)


def insert_sample_data_sync(conn) -> None:
    """Insert sample data for testing (synchronous)."""
    with conn.cursor() as cur:
        cur.execute(SAMPLE_DATA_SQL)
        conn.commit()


# =============================================================================
# CLI for Testing
# =============================================================================

if __name__ == "__main__":
    import asyncio

    async def main():
        """Test schema application."""
        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            print("DATABASE_URL environment variable not set")
            print("Example: postgresql://user:password@host/database?sslmode=require")
            return

        try:
            import asyncpg
        except ImportError:
            print("asyncpg not installed. Install with: pip install asyncpg")
            return

        print("Connecting to database...")
        pool = await asyncpg.create_pool(
            database_url,
            min_size=1,
            max_size=5,
            command_timeout=60
        )

        try:
            print("Applying schema v2...")
            await apply_schema_v2(pool)
            print("Schema v2 applied successfully!")

            print("\nInserting sample data...")
            await insert_sample_data(pool)
            print("Sample data inserted!")

            # Verify tables exist
            async with pool.acquire() as conn:
                tables = await conn.fetch("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    ORDER BY table_name
                """)

                print("\nCreated tables:")
                for table in tables:
                    print(f"  - {table['table_name']}")

                # Count records in each table
                print("\nRecord counts:")
                for table in tables:
                    count = await conn.fetchval(f"SELECT COUNT(*) FROM {table['table_name']}")
                    print(f"  - {table['table_name']}: {count} records")

        finally:
            await pool.close()
            print("\nDone!")

    asyncio.run(main())
