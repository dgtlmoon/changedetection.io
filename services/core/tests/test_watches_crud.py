"""PgWatchStore — full CRUD + scheduler hook + cross-tenant isolation."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.db import with_current_org
from app.store import PgWatchStore

pytestmark = pytest.mark.db


async def _create_watch(store: PgWatchStore, *, org_id, url: str = "https://example.test"):
    async with with_current_org(org_id) as db:
        w = await store.create(db, org_id=org_id, url=url, title="Example")
    return w


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_then_get(org_id) -> None:
    store = PgWatchStore()
    w = await _create_watch(store, org_id=org_id)

    async with with_current_org(org_id) as db:
        hit = await store.get(db, org_id=org_id, watch_id=w.id)

    assert hit is not None
    assert hit.url == "https://example.test"
    assert hit.title == "Example"
    assert hit.paused is False
    assert hit.processor == "text_json_diff"
    assert hit.check_count == 0
    assert hit.settings == {}


@pytest.mark.asyncio
async def test_list_returns_newest_first(org_id) -> None:
    store = PgWatchStore()
    urls = [f"https://example.test/{i}" for i in range(3)]
    for u in urls:
        await _create_watch(store, org_id=org_id, url=u)

    async with with_current_org(org_id) as db:
        rows = await store.list(db, org_id=org_id)
    assert [r.url for r in rows] == list(reversed(urls))


@pytest.mark.asyncio
async def test_update_applies_patch(org_id) -> None:
    store = PgWatchStore()
    w = await _create_watch(store, org_id=org_id)

    async with with_current_org(org_id) as db:
        updated = await store.update(
            db,
            org_id=org_id,
            watch_id=w.id,
            patch={"title": "Renamed", "paused": True},
        )
    assert updated is not None
    assert updated.title == "Renamed"
    assert updated.paused is True

    # Re-fetch to confirm persistence.
    async with with_current_org(org_id) as db:
        fresh = await store.get(db, org_id=org_id, watch_id=w.id)
    assert fresh.title == "Renamed"
    assert fresh.paused is True


@pytest.mark.asyncio
async def test_update_unknown_watch_returns_none(org_id) -> None:
    store = PgWatchStore()
    async with with_current_org(org_id) as db:
        got = await store.update(
            db, org_id=org_id, watch_id=uuid4(), patch={"title": "x"}
        )
    assert got is None


@pytest.mark.asyncio
async def test_update_rejects_unknown_field(org_id) -> None:
    store = PgWatchStore()
    w = await _create_watch(store, org_id=org_id)
    async with with_current_org(org_id) as db:
        with pytest.raises(ValueError):
            await store.update(
                db,
                org_id=org_id,
                watch_id=w.id,
                patch={"not_a_real_field": True},  # type: ignore[typeddict-unknown-key]
            )


@pytest.mark.asyncio
async def test_delete_is_soft(org_id) -> None:
    store = PgWatchStore()
    w = await _create_watch(store, org_id=org_id)

    async with with_current_org(org_id) as db:
        assert await store.delete(db, org_id=org_id, watch_id=w.id) is True

    # Subsequent get / list should not see it.
    async with with_current_org(org_id) as db:
        assert await store.get(db, org_id=org_id, watch_id=w.id) is None
        rows = await store.list(db, org_id=org_id)
    assert rows == []

    # Second delete returns False (idempotent).
    async with with_current_org(org_id) as db:
        assert await store.delete(db, org_id=org_id, watch_id=w.id) is False


# ---------------------------------------------------------------------------
# mark_checked — worker hook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_checked_increments_and_stamps(org_id) -> None:
    store = PgWatchStore()
    w = await _create_watch(store, org_id=org_id)

    async with with_current_org(org_id) as db:
        ok = await store.mark_checked(
            db,
            org_id=org_id,
            watch_id=w.id,
            changed=True,
            previous_md5="abc123",
        )
    assert ok is True

    async with with_current_org(org_id) as db:
        fresh = await store.get(db, org_id=org_id, watch_id=w.id)
    assert fresh.check_count == 1
    assert fresh.last_checked is not None
    assert fresh.last_changed is not None
    assert fresh.previous_md5 == "abc123"
    assert fresh.last_error is None


@pytest.mark.asyncio
async def test_mark_checked_error_path(org_id) -> None:
    store = PgWatchStore()
    w = await _create_watch(store, org_id=org_id)

    async with with_current_org(org_id) as db:
        ok = await store.mark_checked(
            db,
            org_id=org_id,
            watch_id=w.id,
            changed=False,
            error="dns lookup failed",
        )
    assert ok is True

    async with with_current_org(org_id) as db:
        fresh = await store.get(db, org_id=org_id, watch_id=w.id)
    assert fresh.last_error == "dns lookup failed"
    assert fresh.last_changed is None


# ---------------------------------------------------------------------------
# Cross-tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_org_b_cannot_read_org_a_watch(org_id, other_org_id) -> None:
    store = PgWatchStore()
    w = await _create_watch(store, org_id=org_id)

    # Org B scope — same watch_id must not resolve.
    async with with_current_org(other_org_id) as db:
        hit = await store.get(db, org_id=other_org_id, watch_id=w.id)
    assert hit is None


@pytest.mark.asyncio
async def test_list_only_returns_current_org_watches(org_id, other_org_id) -> None:
    store = PgWatchStore()
    await _create_watch(store, org_id=org_id, url="https://example.test/a")
    await _create_watch(
        store, org_id=other_org_id, url="https://example.test/b"
    )

    async with with_current_org(org_id) as db:
        rows = await store.list(db, org_id=org_id)
    urls = {r.url for r in rows}
    assert urls == {"https://example.test/a"}


@pytest.mark.asyncio
async def test_org_b_cannot_delete_org_a_watch(org_id, other_org_id) -> None:
    store = PgWatchStore()
    w = await _create_watch(store, org_id=org_id)

    async with with_current_org(other_org_id) as db:
        ok = await store.delete(db, org_id=other_org_id, watch_id=w.id)
    assert ok is False

    async with with_current_org(org_id) as db:
        hit = await store.get(db, org_id=org_id, watch_id=w.id)
    assert hit is not None  # still alive


@pytest.mark.asyncio
async def test_org_b_cannot_update_org_a_watch(org_id, other_org_id) -> None:
    store = PgWatchStore()
    w = await _create_watch(store, org_id=org_id)

    async with with_current_org(other_org_id) as db:
        got = await store.update(
            db, org_id=other_org_id, watch_id=w.id, patch={"title": "hijack"}
        )
    assert got is None

    async with with_current_org(org_id) as db:
        fresh = await store.get(db, org_id=org_id, watch_id=w.id)
    assert fresh.title == "Example"
