"""Async engine + tenant-scoped session helpers for the core service.

Mirrors the identity service's layout so the two services have a
consistent shape. A thin duplication is deliberate — it keeps the
services independent at the package level.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import get_settings

_settings = get_settings()


def _make_engine(url: str) -> AsyncEngine:
    return create_async_engine(
        url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=10,
        future=True,
    )


engine: AsyncEngine = _make_engine(_settings.database_url)
admin_engine: AsyncEngine = _make_engine(_settings.database_admin_url)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False, autoflush=False
)
AsyncAdminSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    admin_engine, expire_on_commit=False, autoflush=False
)


@asynccontextmanager
async def with_current_org(org_id: UUID | None) -> AsyncIterator[AsyncSession]:
    """Yield an RLS-respecting session bound to ``org_id``.

    Sets ``app.current_org`` for the lifetime of the transaction so
    RLS policies on ``watches``, ``watch_tags``, and ``watch_tag_links``
    evaluate correctly. ``None`` clears the setting — any tenant-scoped
    query then returns zero rows, which surfaces a missing context
    loudly in tests instead of silently leaking cross-tenant data.
    """
    session = AsyncSessionLocal()
    try:
        await session.begin()
        if org_id is None:
            await session.execute(text("SELECT set_config('app.current_org', '', true)"))
        else:
            await session.execute(
                text("SELECT set_config('app.current_org', :org_id, true)"),
                {"org_id": str(org_id)},
            )
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


@asynccontextmanager
async def admin_session() -> AsyncIterator[AsyncSession]:
    """Yield a ``BYPASSRLS`` session. Used by migrations and ops only."""
    session = AsyncAdminSessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
