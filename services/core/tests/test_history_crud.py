"""PgHistoryStore — record, list, get, delete, cross-tenant isolation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.db import with_current_org
from app.store import PgHistoryStore, PgWatchStore

pytestmark = pytest.mark.db


def _now_minus(minutes: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=minutes)


async def _make_watch(store: PgWatchStore, *, org_id, url: str = "https://example.test"):
    async with with_current_org(org_id) as db:
        return await store.create(db, org_id=org_id, url=url)


async def _record(
    hist: PgHistoryStore,
    *,
    org_id,
    watch_id,
    kind: str = "snapshot",
    taken_at: datetime | None = None,
    object_key: str | None = None,
):
    object_key = object_key or f"org/{org_id}/watches/{watch_id}/snap/{uuid4().hex}.brotli"
    async with with_current_org(org_id) as db:
        return await hist.record(
            db,
            org_id=org_id,
            watch_id=watch_id,
            taken_at=taken_at or datetime.now(timezone.utc),
            kind=kind,
            content_type="text/plain",
            object_key=object_key,
            size_bytes=42,
            hash_md5="d41d8cd98f00b204e9800998ecf8427e",
        )


@pytest.mark.asyncio
async def test_record_then_get(org_id) -> None:
    ws, hs = PgWatchStore(), PgHistoryStore()
    w = await _make_watch(ws, org_id=org_id)
    row = await _record(hs, org_id=org_id, watch_id=w.id)

    async with with_current_org(org_id) as db:
        hit = await hs.get(db, org_id=org_id, watch_id=w.id, entry_id=row.id)
    assert hit is not None
    assert hit.kind == "snapshot"
    assert hit.size_bytes == 42


@pytest.mark.asyncio
async def test_list_newest_first(org_id) -> None:
    ws, hs = PgWatchStore(), PgHistoryStore()
    w = await _make_watch(ws, org_id=org_id)
    for m in [30, 20, 10, 5]:
        await _record(hs, org_id=org_id, watch_id=w.id, taken_at=_now_minus(m))

    async with with_current_org(org_id) as db:
        rows = await hs.list(db, org_id=org_id, watch_id=w.id)
    # Monotonically decreasing taken_at (newest first).
    times = [r.taken_at for r in rows]
    assert times == sorted(times, reverse=True)


@pytest.mark.asyncio
async def test_list_kind_filter(org_id) -> None:
    ws, hs = PgWatchStore(), PgHistoryStore()
    w = await _make_watch(ws, org_id=org_id)
    await _record(hs, org_id=org_id, watch_id=w.id, kind="snapshot")
    await _record(hs, org_id=org_id, watch_id=w.id, kind="screenshot")

    async with with_current_org(org_id) as db:
        shots = await hs.list(
            db, org_id=org_id, watch_id=w.id, kind="screenshot"
        )
    assert len(shots) == 1
    assert shots[0].kind == "screenshot"


@pytest.mark.asyncio
async def test_list_pagination(org_id) -> None:
    ws, hs = PgWatchStore(), PgHistoryStore()
    w = await _make_watch(ws, org_id=org_id)
    for m in range(10, 0, -1):
        await _record(hs, org_id=org_id, watch_id=w.id, taken_at=_now_minus(m))

    async with with_current_org(org_id) as db:
        page1 = await hs.list(db, org_id=org_id, watch_id=w.id, limit=3)
        page2 = await hs.list(
            db, org_id=org_id, watch_id=w.id, limit=3, offset=3
        )
    assert len(page1) == 3
    assert len(page2) == 3
    assert {r.id for r in page1}.isdisjoint({r.id for r in page2})


@pytest.mark.asyncio
async def test_delete_returns_object_key(org_id) -> None:
    ws, hs = PgWatchStore(), PgHistoryStore()
    w = await _make_watch(ws, org_id=org_id)
    row = await _record(hs, org_id=org_id, watch_id=w.id)
    key = row.object_key

    async with with_current_org(org_id) as db:
        deleted, returned_key = await hs.delete(
            db, org_id=org_id, watch_id=w.id, entry_id=row.id
        )
    assert deleted is True
    assert returned_key == key

    # Second delete is a no-op.
    async with with_current_org(org_id) as db:
        deleted2, returned_key2 = await hs.delete(
            db, org_id=org_id, watch_id=w.id, entry_id=row.id
        )
    assert deleted2 is False
    assert returned_key2 is None


@pytest.mark.asyncio
async def test_unknown_kind_raises(org_id) -> None:
    ws, hs = PgWatchStore(), PgHistoryStore()
    w = await _make_watch(ws, org_id=org_id)
    async with with_current_org(org_id) as db:
        with pytest.raises(ValueError):
            await hs.record(
                db,
                org_id=org_id,
                watch_id=w.id,
                taken_at=datetime.now(timezone.utc),
                kind="lol-nope",
                content_type="text/plain",
                object_key=f"org/{org_id}/k",
                size_bytes=1,
                hash_md5="x",
            )


# ---------------------------------------------------------------------------
# Cross-tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_in_wrong_org_raises(org_id, other_org_id) -> None:
    ws, hs = PgWatchStore(), PgHistoryStore()
    w = await _make_watch(ws, org_id=org_id)

    # Try to record a history entry while scoped to a different org.
    async with with_current_org(other_org_id) as db:
        with pytest.raises(ValueError):
            await hs.record(
                db,
                org_id=other_org_id,
                watch_id=w.id,
                taken_at=datetime.now(timezone.utc),
                kind="snapshot",
                content_type="text/plain",
                object_key=f"other/{w.id}/x",
                size_bytes=1,
                hash_md5="x",
            )


@pytest.mark.asyncio
async def test_cross_tenant_read_returns_empty(org_id, other_org_id) -> None:
    ws, hs = PgWatchStore(), PgHistoryStore()
    w = await _make_watch(ws, org_id=org_id)
    row = await _record(hs, org_id=org_id, watch_id=w.id)

    async with with_current_org(other_org_id) as db:
        miss = await hs.get(
            db, org_id=other_org_id, watch_id=w.id, entry_id=row.id
        )
        listed = await hs.list(db, org_id=other_org_id, watch_id=w.id)
    assert miss is None
    assert listed == []


@pytest.mark.asyncio
async def test_cross_tenant_delete_is_noop(org_id, other_org_id) -> None:
    ws, hs = PgWatchStore(), PgHistoryStore()
    w = await _make_watch(ws, org_id=org_id)
    row = await _record(hs, org_id=org_id, watch_id=w.id)

    async with with_current_org(other_org_id) as db:
        deleted, _ = await hs.delete(
            db, org_id=other_org_id, watch_id=w.id, entry_id=row.id
        )
    assert deleted is False

    # Row still there when queried from the correct org.
    async with with_current_org(org_id) as db:
        still = await hs.get(db, org_id=org_id, watch_id=w.id, entry_id=row.id)
    assert still is not None
