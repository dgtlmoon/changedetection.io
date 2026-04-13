"""Async SQLAlchemy engine, session factory, and RLS helpers.

Two engines are exposed:

* ``engine`` — connects as the ``app_runtime`` role. Row-Level Security
  policies apply. This is what the request hot path uses, and it only
  returns rows whose ``org_id`` matches the ``app.current_org`` session
  variable set by :func:`with_current_org`.
* ``admin_engine`` — connects as ``identity_admin`` which has
  ``BYPASSRLS``. Used **only** from the identity service's internal
  cross-org lookups (e.g. "given an email and a password, which orgs
  does this user belong to"). Every call site must be auditable.
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
        # The only dialect the app speaks is Postgres 15+.
        future=True,
    )


engine: AsyncEngine = _make_engine(_settings.database_url)
admin_engine: AsyncEngine = _make_engine(_settings.database_admin_url)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    expire_on_commit=False,
    autoflush=False,
)
AsyncAdminSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    admin_engine,
    expire_on_commit=False,
    autoflush=False,
)


@asynccontextmanager
async def with_current_org(org_id: UUID | None) -> AsyncIterator[AsyncSession]:
    """Yield an RLS-respecting session bound to ``org_id``.

    Sets the Postgres session variable ``app.current_org`` for the
    lifetime of the transaction. RLS policies read this value, so any
    ``SELECT`` that forgets to filter by ``org_id`` still returns only
    rows owned by the current tenant (belt + suspenders).

    If ``org_id`` is ``None`` (e.g. a public route that legitimately has
    no tenant), the setting is cleared; any tenant-scoped query will
    return zero rows, which surfaces the mistake loudly in tests.
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
    """Yield a ``BYPASSRLS`` session.

    Use sparingly — every call site is a potential cross-tenant leak
    risk. Wrap the block in a concrete, narrow function (e.g.
    ``find_user_by_email``) rather than passing the session around.
    """
    session = AsyncAdminSessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
