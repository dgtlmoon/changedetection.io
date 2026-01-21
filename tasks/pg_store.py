"""
PostgreSQL Storage Adapter for TicketWatch

This module provides a PostgreSQL-based storage adapter that can be used
alongside or instead of the default JSON-based storage in changedetection.io.

Tables:
- watches: Stores watch configurations
- snapshots: Stores content snapshots with extracted data

Usage:
    from tasks.pg_store import PostgreSQLStore

    store = PostgreSQLStore(database_url=os.getenv('DATABASE_URL'))
    await store.initialize()
"""

import os
import hashlib
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
from contextlib import asynccontextmanager

# PostgreSQL async driver
try:
    import asyncpg
    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False

# Synchronous fallback
try:
    import psycopg2
    import psycopg2.extras
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

# Try to use loguru if available (part of changedetection.io dependencies)
try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class WatchRecord:
    """Database record for a watch configuration"""
    id: str  # UUID
    url: str
    title: Optional[str] = None
    tag: Optional[str] = None
    check_interval: int = 3600  # seconds
    last_checked: Optional[datetime] = None
    last_changed: Optional[datetime] = None
    paused: bool = False
    created_at: Optional[datetime] = None

    # Extended fields for full compatibility
    processor: str = 'text_json_diff'
    fetch_backend: str = 'html_requests'
    include_filters: Optional[List[str]] = None
    headers: Optional[Dict[str, str]] = None
    notification_urls: Optional[List[str]] = None
    extra_config: Optional[Dict[str, Any]] = None  # JSON blob for additional settings

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        result = asdict(self)
        # Convert datetime objects to ISO strings
        for key in ['last_checked', 'last_changed', 'created_at']:
            if result[key] is not None:
                result[key] = result[key].isoformat()
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'WatchRecord':
        """Create from dictionary"""
        # Convert ISO strings back to datetime
        for key in ['last_checked', 'last_changed', 'created_at']:
            if data.get(key) and isinstance(data[key], str):
                data[key] = datetime.fromisoformat(data[key])
        return cls(**data)


@dataclass
class SnapshotRecord:
    """Database record for a content snapshot"""
    id: str  # UUID
    watch_id: str  # Foreign key to watches
    content_hash: str  # MD5 hash of content
    captured_at: datetime
    extracted_prices: Optional[List[Dict[str, Any]]] = None  # JSON array of price data
    extracted_availability: Optional[str] = None  # in_stock, out_of_stock, unknown

    # Content storage options
    content_text: Optional[str] = None  # For small text content
    content_url: Optional[str] = None  # For external storage (S3, etc.)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        result = asdict(self)
        if result['captured_at'] is not None:
            result['captured_at'] = result['captured_at'].isoformat()
        return result


# =============================================================================
# SQL Schema Definitions
# =============================================================================

SCHEMA_VERSION = 1

CREATE_WATCHES_TABLE = """
CREATE TABLE IF NOT EXISTS watches (
    id UUID PRIMARY KEY,
    url TEXT NOT NULL,
    title TEXT,
    tag TEXT,
    check_interval INTEGER DEFAULT 3600,
    last_checked TIMESTAMP WITH TIME ZONE,
    last_changed TIMESTAMP WITH TIME ZONE,
    paused BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Extended fields
    processor TEXT DEFAULT 'text_json_diff',
    fetch_backend TEXT DEFAULT 'html_requests',
    include_filters JSONB DEFAULT '[]'::jsonb,
    headers JSONB DEFAULT '{}'::jsonb,
    notification_urls JSONB DEFAULT '[]'::jsonb,
    extra_config JSONB DEFAULT '{}'::jsonb,

    -- Indexes will be created separately
    CONSTRAINT watches_url_not_empty CHECK (url <> '')
);
"""

CREATE_SNAPSHOTS_TABLE = """
CREATE TABLE IF NOT EXISTS snapshots (
    id UUID PRIMARY KEY,
    watch_id UUID NOT NULL REFERENCES watches(id) ON DELETE CASCADE,
    content_hash TEXT NOT NULL,
    captured_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    extracted_prices JSONB,
    extracted_availability TEXT,
    content_text TEXT,
    content_url TEXT,

    CONSTRAINT snapshots_watch_fk FOREIGN KEY (watch_id)
        REFERENCES watches(id) ON DELETE CASCADE
);
"""

CREATE_SCHEMA_VERSION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_watches_url ON watches(url);",
    "CREATE INDEX IF NOT EXISTS idx_watches_tag ON watches(tag);",
    "CREATE INDEX IF NOT EXISTS idx_watches_last_checked ON watches(last_checked);",
    "CREATE INDEX IF NOT EXISTS idx_watches_paused ON watches(paused);",
    "CREATE INDEX IF NOT EXISTS idx_snapshots_watch_id ON snapshots(watch_id);",
    "CREATE INDEX IF NOT EXISTS idx_snapshots_captured_at ON snapshots(captured_at);",
    "CREATE INDEX IF NOT EXISTS idx_snapshots_content_hash ON snapshots(content_hash);",
]


# =============================================================================
# PostgreSQL Store Implementation
# =============================================================================

class PostgreSQLStore:
    """
    PostgreSQL storage adapter for TicketWatch.

    Provides async methods for storing and retrieving watch configurations
    and content snapshots.
    """

    def __init__(self, database_url: Optional[str] = None):
        """
        Initialize the PostgreSQL store.

        Args:
            database_url: PostgreSQL connection string. If not provided,
                         reads from DATABASE_URL environment variable.
        """
        self.database_url = database_url or os.getenv('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL must be provided or set as environment variable")

        self._pool: Optional[asyncpg.Pool] = None
        self._sync_conn = None

    # -------------------------------------------------------------------------
    # Connection Management
    # -------------------------------------------------------------------------

    async def initialize(self) -> None:
        """Initialize the database connection pool and create tables."""
        if not HAS_ASYNCPG:
            raise ImportError("asyncpg is required for async PostgreSQL support. Install with: pip install asyncpg")

        logger.info("Initializing PostgreSQL connection pool...")
        self._pool = await asyncpg.create_pool(
            self.database_url,
            min_size=2,
            max_size=10,
            command_timeout=60
        )

        await self._create_schema()
        logger.info("PostgreSQL store initialized successfully")

    async def close(self) -> None:
        """Close the database connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("PostgreSQL connection pool closed")

    @asynccontextmanager
    async def acquire(self):
        """Acquire a connection from the pool."""
        if not self._pool:
            raise RuntimeError("Store not initialized. Call initialize() first.")
        async with self._pool.acquire() as conn:
            yield conn

    def initialize_sync(self) -> None:
        """Initialize synchronous database connection (fallback)."""
        if not HAS_PSYCOPG2:
            raise ImportError("psycopg2 is required for sync PostgreSQL support. Install with: pip install psycopg2-binary")

        logger.info("Initializing synchronous PostgreSQL connection...")
        self._sync_conn = psycopg2.connect(self.database_url)
        self._create_schema_sync()
        logger.info("PostgreSQL store initialized successfully (sync mode)")

    def close_sync(self) -> None:
        """Close the synchronous database connection."""
        if self._sync_conn:
            self._sync_conn.close()
            self._sync_conn = None

    # -------------------------------------------------------------------------
    # Schema Management
    # -------------------------------------------------------------------------

    async def _create_schema(self) -> None:
        """Create database tables and indexes."""
        async with self.acquire() as conn:
            # Create schema version table
            await conn.execute(CREATE_SCHEMA_VERSION_TABLE)

            # Check current schema version
            current_version = await conn.fetchval(
                "SELECT COALESCE(MAX(version), 0) FROM schema_version"
            )

            if current_version < SCHEMA_VERSION:
                logger.info(f"Upgrading schema from version {current_version} to {SCHEMA_VERSION}")

                # Create tables
                await conn.execute(CREATE_WATCHES_TABLE)
                await conn.execute(CREATE_SNAPSHOTS_TABLE)

                # Create indexes
                for index_sql in CREATE_INDEXES:
                    await conn.execute(index_sql)

                # Record schema version
                await conn.execute(
                    "INSERT INTO schema_version (version) VALUES ($1) ON CONFLICT DO NOTHING",
                    SCHEMA_VERSION
                )

                logger.info("Schema upgrade complete")

    def _create_schema_sync(self) -> None:
        """Create database tables and indexes (synchronous version)."""
        with self._sync_conn.cursor() as cur:
            # Create schema version table
            cur.execute(CREATE_SCHEMA_VERSION_TABLE)

            # Check current schema version
            cur.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version")
            current_version = cur.fetchone()[0]

            if current_version < SCHEMA_VERSION:
                logger.info(f"Upgrading schema from version {current_version} to {SCHEMA_VERSION}")

                # Create tables
                cur.execute(CREATE_WATCHES_TABLE)
                cur.execute(CREATE_SNAPSHOTS_TABLE)

                # Create indexes
                for index_sql in CREATE_INDEXES:
                    cur.execute(index_sql)

                # Record schema version
                cur.execute(
                    "INSERT INTO schema_version (version) VALUES (%s) ON CONFLICT DO NOTHING",
                    (SCHEMA_VERSION,)
                )

                self._sync_conn.commit()
                logger.info("Schema upgrade complete")

    # -------------------------------------------------------------------------
    # Watch CRUD Operations (Async)
    # -------------------------------------------------------------------------

    async def add_watch(self, watch: WatchRecord) -> str:
        """
        Add a new watch to the database.

        Args:
            watch: WatchRecord instance

        Returns:
            The watch ID (UUID)
        """
        async with self.acquire() as conn:
            await conn.execute("""
                INSERT INTO watches (
                    id, url, title, tag, check_interval, last_checked,
                    last_changed, paused, created_at, processor, fetch_backend,
                    include_filters, headers, notification_urls, extra_config
                ) VALUES (
                    $1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
                    $12::jsonb, $13::jsonb, $14::jsonb, $15::jsonb
                )
            """,
                watch.id,
                watch.url,
                watch.title,
                watch.tag,
                watch.check_interval,
                watch.last_checked,
                watch.last_changed,
                watch.paused,
                watch.created_at or datetime.utcnow(),
                watch.processor,
                watch.fetch_backend,
                json.dumps(watch.include_filters or []),
                json.dumps(watch.headers or {}),
                json.dumps(watch.notification_urls or []),
                json.dumps(watch.extra_config or {})
            )
            logger.debug(f"Added watch: {watch.id} - {watch.url}")
            return watch.id

    async def get_watch(self, watch_id: str) -> Optional[WatchRecord]:
        """
        Get a watch by ID.

        Args:
            watch_id: UUID of the watch

        Returns:
            WatchRecord or None if not found
        """
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM watches WHERE id = $1::uuid",
                watch_id
            )
            if row:
                return self._row_to_watch(row)
            return None

    async def get_watch_by_url(self, url: str) -> Optional[WatchRecord]:
        """
        Get a watch by URL.

        Args:
            url: URL to search for

        Returns:
            WatchRecord or None if not found
        """
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM watches WHERE url = $1",
                url
            )
            if row:
                return self._row_to_watch(row)
            return None

    async def get_all_watches(
        self,
        tag: Optional[str] = None,
        paused: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[WatchRecord]:
        """
        Get all watches with optional filtering.

        Args:
            tag: Filter by tag
            paused: Filter by paused status
            limit: Maximum number of results
            offset: Skip first N results

        Returns:
            List of WatchRecord instances
        """
        async with self.acquire() as conn:
            query = "SELECT * FROM watches WHERE 1=1"
            params = []
            param_count = 0

            if tag is not None:
                param_count += 1
                query += f" AND tag = ${param_count}"
                params.append(tag)

            if paused is not None:
                param_count += 1
                query += f" AND paused = ${param_count}"
                params.append(paused)

            query += f" ORDER BY created_at DESC LIMIT ${param_count + 1} OFFSET ${param_count + 2}"
            params.extend([limit, offset])

            rows = await conn.fetch(query, *params)
            return [self._row_to_watch(row) for row in rows]

    async def update_watch(self, watch_id: str, updates: Dict[str, Any]) -> bool:
        """
        Update a watch.

        Args:
            watch_id: UUID of the watch
            updates: Dictionary of fields to update

        Returns:
            True if updated, False if not found
        """
        if not updates:
            return False

        # Build dynamic UPDATE query
        set_clauses = []
        params = []
        param_count = 0

        # Map of field names to their types for proper casting
        json_fields = {'include_filters', 'headers', 'notification_urls', 'extra_config'}

        for key, value in updates.items():
            param_count += 1
            if key in json_fields:
                set_clauses.append(f"{key} = ${param_count}::jsonb")
                params.append(json.dumps(value) if value is not None else '{}')
            else:
                set_clauses.append(f"{key} = ${param_count}")
                params.append(value)

        params.append(watch_id)

        query = f"""
            UPDATE watches
            SET {', '.join(set_clauses)}
            WHERE id = ${param_count + 1}::uuid
        """

        async with self.acquire() as conn:
            result = await conn.execute(query, *params)
            return result == "UPDATE 1"

    async def delete_watch(self, watch_id: str) -> bool:
        """
        Delete a watch and its snapshots.

        Args:
            watch_id: UUID of the watch

        Returns:
            True if deleted, False if not found
        """
        async with self.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM watches WHERE id = $1::uuid",
                watch_id
            )
            deleted = result == "DELETE 1"
            if deleted:
                logger.debug(f"Deleted watch: {watch_id}")
            return deleted

    async def url_exists(self, url: str) -> bool:
        """Check if a URL is already being watched."""
        async with self.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM watches WHERE url = $1",
                url
            )
            return count > 0

    # -------------------------------------------------------------------------
    # Snapshot CRUD Operations (Async)
    # -------------------------------------------------------------------------

    async def add_snapshot(self, snapshot: SnapshotRecord) -> str:
        """
        Add a new snapshot.

        Args:
            snapshot: SnapshotRecord instance

        Returns:
            The snapshot ID (UUID)
        """
        async with self.acquire() as conn:
            await conn.execute("""
                INSERT INTO snapshots (
                    id, watch_id, content_hash, captured_at,
                    extracted_prices, extracted_availability,
                    content_text, content_url
                ) VALUES (
                    $1::uuid, $2::uuid, $3, $4, $5::jsonb, $6, $7, $8
                )
            """,
                snapshot.id,
                snapshot.watch_id,
                snapshot.content_hash,
                snapshot.captured_at or datetime.utcnow(),
                json.dumps(snapshot.extracted_prices) if snapshot.extracted_prices else None,
                snapshot.extracted_availability,
                snapshot.content_text,
                snapshot.content_url
            )
            logger.debug(f"Added snapshot: {snapshot.id} for watch {snapshot.watch_id}")
            return snapshot.id

    async def get_snapshots(
        self,
        watch_id: str,
        limit: int = 50,
        offset: int = 0
    ) -> List[SnapshotRecord]:
        """
        Get snapshots for a watch.

        Args:
            watch_id: UUID of the watch
            limit: Maximum number of results
            offset: Skip first N results

        Returns:
            List of SnapshotRecord instances
        """
        async with self.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM snapshots
                WHERE watch_id = $1::uuid
                ORDER BY captured_at DESC
                LIMIT $2 OFFSET $3
            """, watch_id, limit, offset)

            return [self._row_to_snapshot(row) for row in rows]

    async def get_latest_snapshot(self, watch_id: str) -> Optional[SnapshotRecord]:
        """Get the most recent snapshot for a watch."""
        async with self.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM snapshots
                WHERE watch_id = $1::uuid
                ORDER BY captured_at DESC
                LIMIT 1
            """, watch_id)

            if row:
                return self._row_to_snapshot(row)
            return None

    async def delete_old_snapshots(self, watch_id: str, keep_count: int = 50) -> int:
        """
        Delete old snapshots, keeping the most recent ones.

        Args:
            watch_id: UUID of the watch
            keep_count: Number of recent snapshots to keep

        Returns:
            Number of deleted snapshots
        """
        async with self.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM snapshots
                WHERE watch_id = $1::uuid
                AND id NOT IN (
                    SELECT id FROM snapshots
                    WHERE watch_id = $1::uuid
                    ORDER BY captured_at DESC
                    LIMIT $2
                )
            """, watch_id, keep_count)

            # Parse "DELETE N" result
            if result.startswith("DELETE "):
                deleted = int(result.split()[1])
                if deleted > 0:
                    logger.debug(f"Deleted {deleted} old snapshots for watch {watch_id}")
                return deleted
            return 0

    # -------------------------------------------------------------------------
    # Synchronous Operations (Fallback)
    # -------------------------------------------------------------------------

    def add_watch_sync(self, watch: WatchRecord) -> str:
        """Add a watch (synchronous version)."""
        with self._sync_conn.cursor() as cur:
            cur.execute("""
                INSERT INTO watches (
                    id, url, title, tag, check_interval, last_checked,
                    last_changed, paused, created_at, processor, fetch_backend,
                    include_filters, headers, notification_urls, extra_config
                ) VALUES (
                    %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb
                )
            """, (
                watch.id,
                watch.url,
                watch.title,
                watch.tag,
                watch.check_interval,
                watch.last_checked,
                watch.last_changed,
                watch.paused,
                watch.created_at or datetime.utcnow(),
                watch.processor,
                watch.fetch_backend,
                json.dumps(watch.include_filters or []),
                json.dumps(watch.headers or {}),
                json.dumps(watch.notification_urls or []),
                json.dumps(watch.extra_config or {})
            ))
            self._sync_conn.commit()
            return watch.id

    def get_watch_sync(self, watch_id: str) -> Optional[WatchRecord]:
        """Get a watch by ID (synchronous version)."""
        with self._sync_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM watches WHERE id = %s::uuid", (watch_id,))
            row = cur.fetchone()
            if row:
                return self._dict_to_watch(dict(row))
            return None

    def get_all_watches_sync(self, tag: Optional[str] = None) -> List[WatchRecord]:
        """Get all watches (synchronous version)."""
        with self._sync_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if tag:
                cur.execute(
                    "SELECT * FROM watches WHERE tag = %s ORDER BY created_at DESC",
                    (tag,)
                )
            else:
                cur.execute("SELECT * FROM watches ORDER BY created_at DESC")

            rows = cur.fetchall()
            return [self._dict_to_watch(dict(row)) for row in rows]

    def add_snapshot_sync(self, snapshot: SnapshotRecord) -> str:
        """Add a snapshot (synchronous version)."""
        with self._sync_conn.cursor() as cur:
            cur.execute("""
                INSERT INTO snapshots (
                    id, watch_id, content_hash, captured_at,
                    extracted_prices, extracted_availability,
                    content_text, content_url
                ) VALUES (
                    %s::uuid, %s::uuid, %s, %s, %s::jsonb, %s, %s, %s
                )
            """, (
                snapshot.id,
                snapshot.watch_id,
                snapshot.content_hash,
                snapshot.captured_at or datetime.utcnow(),
                json.dumps(snapshot.extracted_prices) if snapshot.extracted_prices else None,
                snapshot.extracted_availability,
                snapshot.content_text,
                snapshot.content_url
            ))
            self._sync_conn.commit()
            return snapshot.id

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def _row_to_watch(self, row: Any) -> WatchRecord:
        """Convert an asyncpg row to WatchRecord."""
        return WatchRecord(
            id=str(row['id']),
            url=row['url'],
            title=row['title'],
            tag=row['tag'],
            check_interval=row['check_interval'],
            last_checked=row['last_checked'],
            last_changed=row['last_changed'],
            paused=row['paused'],
            created_at=row['created_at'],
            processor=row['processor'],
            fetch_backend=row['fetch_backend'],
            include_filters=row['include_filters'] if row['include_filters'] else [],
            headers=row['headers'] if row['headers'] else {},
            notification_urls=row['notification_urls'] if row['notification_urls'] else [],
            extra_config=row['extra_config'] if row['extra_config'] else {}
        )

    def _dict_to_watch(self, data: Dict[str, Any]) -> WatchRecord:
        """Convert a dictionary to WatchRecord (for psycopg2)."""
        return WatchRecord(
            id=str(data['id']),
            url=data['url'],
            title=data['title'],
            tag=data['tag'],
            check_interval=data['check_interval'],
            last_checked=data['last_checked'],
            last_changed=data['last_changed'],
            paused=data['paused'],
            created_at=data['created_at'],
            processor=data['processor'],
            fetch_backend=data['fetch_backend'],
            include_filters=data['include_filters'] if data['include_filters'] else [],
            headers=data['headers'] if data['headers'] else {},
            notification_urls=data['notification_urls'] if data['notification_urls'] else [],
            extra_config=data['extra_config'] if data['extra_config'] else {}
        )

    def _row_to_snapshot(self, row: Any) -> SnapshotRecord:
        """Convert an asyncpg row to SnapshotRecord."""
        return SnapshotRecord(
            id=str(row['id']),
            watch_id=str(row['watch_id']),
            content_hash=row['content_hash'],
            captured_at=row['captured_at'],
            extracted_prices=row['extracted_prices'],
            extracted_availability=row['extracted_availability'],
            content_text=row['content_text'],
            content_url=row['content_url']
        )

    @staticmethod
    def compute_content_hash(content: str) -> str:
        """Compute MD5 hash of content."""
        return hashlib.md5(content.encode('utf-8')).hexdigest()


# =============================================================================
# Utility Functions
# =============================================================================

def create_watch_from_changedetection(watch_data: Dict[str, Any], uuid: str) -> WatchRecord:
    """
    Create a WatchRecord from changedetection.io's watch data format.

    This helps bridge the existing JSON format to PostgreSQL.
    """
    # Calculate check interval from time_between_check
    check_interval = 3600  # Default 1 hour
    time_between = watch_data.get('time_between_check', {})
    if time_between:
        check_interval = (
            (time_between.get('weeks', 0) or 0) * 604800 +
            (time_between.get('days', 0) or 0) * 86400 +
            (time_between.get('hours', 0) or 0) * 3600 +
            (time_between.get('minutes', 0) or 0) * 60 +
            (time_between.get('seconds', 0) or 0)
        )
        if check_interval == 0:
            check_interval = 3600

    # Convert last_checked from epoch to datetime
    last_checked = None
    if watch_data.get('last_checked'):
        last_checked = datetime.fromtimestamp(watch_data['last_checked'])

    # Convert date_created from epoch to datetime
    created_at = None
    if watch_data.get('date_created'):
        created_at = datetime.fromtimestamp(watch_data['date_created'])

    # Get tags as comma-separated string (simplified)
    tag = watch_data.get('tag', '')

    return WatchRecord(
        id=uuid,
        url=watch_data.get('url', ''),
        title=watch_data.get('title'),
        tag=tag,
        check_interval=check_interval,
        last_checked=last_checked,
        last_changed=None,  # Computed from snapshots
        paused=watch_data.get('paused', False),
        created_at=created_at,
        processor=watch_data.get('processor', 'text_json_diff'),
        fetch_backend=watch_data.get('fetch_backend', 'html_requests'),
        include_filters=watch_data.get('include_filters', []),
        headers=watch_data.get('headers', {}),
        notification_urls=watch_data.get('notification_urls', []),
        extra_config={
            'ignore_text': watch_data.get('ignore_text', []),
            'trigger_text': watch_data.get('trigger_text', []),
            'text_should_not_be_present': watch_data.get('text_should_not_be_present', []),
            'subtractive_selectors': watch_data.get('subtractive_selectors', []),
            'extract_text': watch_data.get('extract_text', []),
        }
    )


# =============================================================================
# CLI for Testing
# =============================================================================

if __name__ == "__main__":
    import asyncio
    import uuid as uuid_lib

    async def test_store():
        """Test the PostgreSQL store."""
        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            print("DATABASE_URL environment variable not set")
            print("Example: postgresql://user:password@host/database")
            return

        store = PostgreSQLStore(database_url)

        try:
            await store.initialize()
            print("Store initialized successfully!")

            # Test adding a watch
            test_watch = WatchRecord(
                id=str(uuid_lib.uuid4()),
                url="https://example.com/tickets",
                title="Test Watch",
                tag="test",
                check_interval=3600,
                paused=False
            )

            watch_id = await store.add_watch(test_watch)
            print(f"Added watch: {watch_id}")

            # Test retrieving the watch
            retrieved = await store.get_watch(watch_id)
            if retrieved:
                print(f"Retrieved watch: {retrieved.url}")

            # Test adding a snapshot
            test_snapshot = SnapshotRecord(
                id=str(uuid_lib.uuid4()),
                watch_id=watch_id,
                content_hash=PostgreSQLStore.compute_content_hash("Test content"),
                captured_at=datetime.utcnow(),
                extracted_prices=[{"price": 99.99, "currency": "USD"}],
                extracted_availability="in_stock",
                content_text="Test content"
            )

            snapshot_id = await store.add_snapshot(test_snapshot)
            print(f"Added snapshot: {snapshot_id}")

            # Test getting snapshots
            snapshots = await store.get_snapshots(watch_id)
            print(f"Found {len(snapshots)} snapshots")

            # Cleanup
            await store.delete_watch(watch_id)
            print("Deleted test watch")

        finally:
            await store.close()

    asyncio.run(test_store())
