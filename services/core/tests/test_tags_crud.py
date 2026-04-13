"""PgTagStore + m2m assign — CRUD, uniqueness, cross-tenant."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.db import with_current_org
from app.store import PgTagStore, PgWatchStore
from app.store.pg import DuplicateTagName

pytestmark = pytest.mark.db


@pytest.mark.asyncio
async def test_create_then_list(org_id) -> None:
    store = PgTagStore()
    async with with_current_org(org_id) as db:
        a = await store.create(db, org_id=org_id, name="news", color="#123")
        b = await store.create(db, org_id=org_id, name="alerts")

    async with with_current_org(org_id) as db:
        rows = await store.list(db, org_id=org_id)
    assert [r.name.lower() for r in rows] == ["alerts", "news"]
    assert {r.id for r in rows} == {a.id, b.id}


@pytest.mark.asyncio
async def test_duplicate_name_within_org_raises(org_id) -> None:
    store = PgTagStore()
    async with with_current_org(org_id) as db:
        await store.create(db, org_id=org_id, name="dupe")

    async with with_current_org(org_id) as db:
        with pytest.raises(DuplicateTagName):
            await store.create(db, org_id=org_id, name="dupe")


@pytest.mark.asyncio
async def test_same_name_in_different_orgs_is_allowed(org_id, other_org_id) -> None:
    store = PgTagStore()
    async with with_current_org(org_id) as db:
        await store.create(db, org_id=org_id, name="shared")
    async with with_current_org(other_org_id) as db:
        await store.create(db, org_id=other_org_id, name="shared")


@pytest.mark.asyncio
async def test_delete_is_soft_and_clears_links(org_id) -> None:
    tag_store = PgTagStore()
    watch_store = PgWatchStore()

    async with with_current_org(org_id) as db:
        tag = await tag_store.create(db, org_id=org_id, name="doomed")
        watch = await watch_store.create(
            db, org_id=org_id, url="https://example.test/watch"
        )
        await tag_store.assign_to_watch(
            db, org_id=org_id, watch_id=watch.id, tag_ids=[tag.id]
        )

    # Confirm link in place.
    async with with_current_org(org_id) as db:
        rows = await watch_store.list(db, org_id=org_id, tag_id=tag.id)
    assert [r.id for r in rows] == [watch.id]

    # Delete the tag.
    async with with_current_org(org_id) as db:
        assert await tag_store.delete(db, org_id=org_id, tag_id=tag.id) is True

    # Tag is gone from list.
    async with with_current_org(org_id) as db:
        rows = await tag_store.list(db, org_id=org_id)
    assert rows == []

    # Watch still exists but no longer tied to the deleted tag.
    async with with_current_org(org_id) as db:
        linked = await watch_store.list(db, org_id=org_id, tag_id=tag.id)
    assert linked == []


# ---------------------------------------------------------------------------
# m2m
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assign_adds_links(org_id) -> None:
    tag_store = PgTagStore()
    watch_store = PgWatchStore()

    async with with_current_org(org_id) as db:
        w = await watch_store.create(db, org_id=org_id, url="https://example.test/w")
        t1 = await tag_store.create(db, org_id=org_id, name="t1")
        t2 = await tag_store.create(db, org_id=org_id, name="t2")
        final = await tag_store.assign_to_watch(
            db, org_id=org_id, watch_id=w.id, tag_ids=[t1.id, t2.id]
        )
    assert {t.name.lower() for t in final} == {"t1", "t2"}


@pytest.mark.asyncio
async def test_assign_replaces_set(org_id) -> None:
    tag_store = PgTagStore()
    watch_store = PgWatchStore()

    async with with_current_org(org_id) as db:
        w = await watch_store.create(db, org_id=org_id, url="https://example.test/w")
        t1 = await tag_store.create(db, org_id=org_id, name="a")
        t2 = await tag_store.create(db, org_id=org_id, name="b")
        t3 = await tag_store.create(db, org_id=org_id, name="c")

        await tag_store.assign_to_watch(
            db, org_id=org_id, watch_id=w.id, tag_ids=[t1.id, t2.id]
        )
        # Replace with {t2, t3}.
        final = await tag_store.assign_to_watch(
            db, org_id=org_id, watch_id=w.id, tag_ids=[t2.id, t3.id]
        )
    assert {t.name.lower() for t in final} == {"b", "c"}


@pytest.mark.asyncio
async def test_assign_empty_removes_all(org_id) -> None:
    tag_store = PgTagStore()
    watch_store = PgWatchStore()

    async with with_current_org(org_id) as db:
        w = await watch_store.create(db, org_id=org_id, url="https://example.test/w")
        t1 = await tag_store.create(db, org_id=org_id, name="k")
        await tag_store.assign_to_watch(
            db, org_id=org_id, watch_id=w.id, tag_ids=[t1.id]
        )
        final = await tag_store.assign_to_watch(
            db, org_id=org_id, watch_id=w.id, tag_ids=[]
        )
    assert final == []


@pytest.mark.asyncio
async def test_assign_ignores_unknown_and_cross_tenant_tags(
    org_id, other_org_id
) -> None:
    tag_store = PgTagStore()
    watch_store = PgWatchStore()

    # Create watch + real tag in org A.
    async with with_current_org(org_id) as db:
        w = await watch_store.create(db, org_id=org_id, url="https://example.test/w")
        t_ok = await tag_store.create(db, org_id=org_id, name="real")

    # Create a tag in org B.
    async with with_current_org(other_org_id) as db:
        t_hostile = await tag_store.create(
            db, org_id=other_org_id, name="hostile"
        )

    # Try to attach: the real tag + a fake id + the cross-tenant tag.
    async with with_current_org(org_id) as db:
        final = await tag_store.assign_to_watch(
            db,
            org_id=org_id,
            watch_id=w.id,
            tag_ids=[t_ok.id, uuid4(), t_hostile.id],
        )
    assert [t.id for t in final] == [t_ok.id]


# ---------------------------------------------------------------------------
# Cross-tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_tenant_get_returns_none(org_id, other_org_id) -> None:
    store = PgTagStore()
    async with with_current_org(org_id) as db:
        t = await store.create(db, org_id=org_id, name="x")

    async with with_current_org(other_org_id) as db:
        hit = await store.get(db, org_id=other_org_id, tag_id=t.id)
    assert hit is None


@pytest.mark.asyncio
async def test_cross_tenant_delete_is_noop(org_id, other_org_id) -> None:
    store = PgTagStore()
    async with with_current_org(org_id) as db:
        t = await store.create(db, org_id=org_id, name="keep")

    async with with_current_org(other_org_id) as db:
        ok = await store.delete(db, org_id=other_org_id, tag_id=t.id)
    assert ok is False

    async with with_current_org(org_id) as db:
        still = await store.get(db, org_id=org_id, tag_id=t.id)
    assert still is not None
