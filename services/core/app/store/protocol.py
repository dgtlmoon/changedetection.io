"""Tenant-scoped store protocols.

Concrete implementations (``PgWatchStore``, ``PgTagStore`` today; a
legacy ``FileStore`` wrapper in Phase 3.3) satisfy these. Route
handlers in Phase 3.2+ will depend on the protocol, not the
implementation.

Every method takes ``org_id`` explicitly and is expected to:
  1. Filter queries on ``org_id`` in the ORM / SQL — the primary
     isolation control.
  2. Run under ``db.with_current_org(org_id)`` so RLS is the safety
     net.

Both are required. CI Postgres runs as a superuser that bypasses RLS
by default, so a missing ORM filter would leak across tenants without
the first control.
"""

from __future__ import annotations

from typing import Any, Protocol, TypedDict
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Watch, WatchTag


class WatchPatch(TypedDict, total=False):
    """Partial update payload. All fields optional; ``None`` means
    "clear the value"; a missing key means "don't touch"."""

    url: str
    title: str | None
    processor: str
    fetch_backend: str
    paused: bool
    notification_muted: bool
    time_between_check_seconds: int | None
    settings: dict[str, Any]


class WatchStore(Protocol):
    async def create(
        self,
        db: AsyncSession,
        *,
        org_id: UUID,
        url: str,
        title: str | None = None,
        processor: str = "text_json_diff",
        fetch_backend: str = "system",
        time_between_check_seconds: int | None = None,
        settings: dict[str, Any] | None = None,
    ) -> Watch: ...

    async def get(
        self, db: AsyncSession, *, org_id: UUID, watch_id: UUID
    ) -> Watch | None: ...

    async def list(
        self,
        db: AsyncSession,
        *,
        org_id: UUID,
        limit: int = 100,
        offset: int = 0,
        paused: bool | None = None,
        tag_id: UUID | None = None,
    ) -> list[Watch]: ...

    async def update(
        self,
        db: AsyncSession,
        *,
        org_id: UUID,
        watch_id: UUID,
        patch: WatchPatch,
    ) -> Watch | None: ...

    async def delete(
        self, db: AsyncSession, *, org_id: UUID, watch_id: UUID
    ) -> bool: ...

    async def mark_checked(
        self,
        db: AsyncSession,
        *,
        org_id: UUID,
        watch_id: UUID,
        changed: bool,
        previous_md5: str | None = None,
        error: str | None = None,
    ) -> bool: ...


class TagStore(Protocol):
    async def create(
        self,
        db: AsyncSession,
        *,
        org_id: UUID,
        name: str,
        color: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> WatchTag: ...

    async def get(
        self, db: AsyncSession, *, org_id: UUID, tag_id: UUID
    ) -> WatchTag | None: ...

    async def list(
        self, db: AsyncSession, *, org_id: UUID
    ) -> list[WatchTag]: ...

    async def delete(
        self, db: AsyncSession, *, org_id: UUID, tag_id: UUID
    ) -> bool: ...

    async def assign_to_watch(
        self,
        db: AsyncSession,
        *,
        org_id: UUID,
        watch_id: UUID,
        tag_ids: list[UUID],
    ) -> list[WatchTag]: ...
