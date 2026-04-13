"""HTTP integration tests for watch CRUD + tag assignment."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from app.db import admin_session

pytestmark = pytest.mark.db


async def _slug_of(org_id) -> str:
    async with admin_session() as db:
        r = await db.execute(
            text("SELECT slug FROM orgs WHERE id = :id"), {"id": str(org_id)}
        )
        return str(r.scalar_one())


# ---------------------------------------------------------------------------
# Auth surface
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_token_is_401(http_client, org_id) -> None:
    slug = await _slug_of(org_id)
    r = await http_client.get(f"/v1/orgs/{slug}/watches")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_garbage_token_is_401(http_client, org_id) -> None:
    slug = await _slug_of(org_id)
    r = await http_client.get(
        f"/v1/orgs/{slug}/watches",
        headers={"Authorization": "Bearer not.a.jwt"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_user_not_in_org_gets_404(
    http_client, org_id, other_org_id, user_factory
) -> None:
    """Member of org B asking about org A must see 404, never 403 —
    that would fingerprint org existence."""
    _, jwt_b = await user_factory(other_org_id, role="owner")
    slug_a = await _slug_of(org_id)
    r = await http_client.get(
        f"/v1/orgs/{slug_a}/watches",
        headers={"Authorization": f"Bearer {jwt_b}"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# CRUD happy paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_then_get(http_client, org_id, user_factory) -> None:
    _, jwt = await user_factory(org_id, role="member")
    slug = await _slug_of(org_id)
    h = {"Authorization": f"Bearer {jwt}"}

    r = await http_client.post(
        f"/v1/orgs/{slug}/watches",
        json={"url": "https://example.test/page", "title": "Example"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["url"] == "https://example.test/page"
    assert body["title"] == "Example"
    assert body["paused"] is False

    g = await http_client.get(f"/v1/orgs/{slug}/watches/{body['id']}", headers=h)
    assert g.status_code == 200
    assert g.json()["id"] == body["id"]


@pytest.mark.asyncio
async def test_list_pagination(http_client, org_id, user_factory) -> None:
    _, jwt = await user_factory(org_id, role="member")
    slug = await _slug_of(org_id)
    h = {"Authorization": f"Bearer {jwt}"}

    for i in range(5):
        r = await http_client.post(
            f"/v1/orgs/{slug}/watches",
            json={"url": f"https://example.test/{i}"},
            headers=h,
        )
        assert r.status_code == 201

    r = await http_client.get(
        f"/v1/orgs/{slug}/watches?limit=2&offset=0", headers=h
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["watches"]) == 2
    assert body["limit"] == 2 and body["offset"] == 0


@pytest.mark.asyncio
async def test_patch_partial_update(http_client, org_id, user_factory) -> None:
    _, jwt = await user_factory(org_id, role="member")
    slug = await _slug_of(org_id)
    h = {"Authorization": f"Bearer {jwt}"}

    created = (
        await http_client.post(
            f"/v1/orgs/{slug}/watches",
            json={"url": "https://example.test/foo"},
            headers=h,
        )
    ).json()

    r = await http_client.patch(
        f"/v1/orgs/{slug}/watches/{created['id']}",
        json={"title": "Renamed", "paused": True},
        headers=h,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Renamed"
    assert body["paused"] is True
    # url untouched
    assert body["url"] == "https://example.test/foo"


@pytest.mark.asyncio
async def test_patch_unknown_field_is_422(http_client, org_id, user_factory) -> None:
    _, jwt = await user_factory(org_id, role="member")
    slug = await _slug_of(org_id)
    h = {"Authorization": f"Bearer {jwt}"}
    created = (
        await http_client.post(
            f"/v1/orgs/{slug}/watches",
            json={"url": "https://example.test/x"},
            headers=h,
        )
    ).json()
    r = await http_client.patch(
        f"/v1/orgs/{slug}/watches/{created['id']}",
        json={"not_a_real_field": True},
        headers=h,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_delete_requires_admin(http_client, org_id, user_factory) -> None:
    _, member_jwt = await user_factory(org_id, role="member")
    _, admin_jwt = await user_factory(org_id, role="admin")
    slug = await _slug_of(org_id)

    created = (
        await http_client.post(
            f"/v1/orgs/{slug}/watches",
            json={"url": "https://example.test/del"},
            headers={"Authorization": f"Bearer {member_jwt}"},
        )
    ).json()

    # member cannot delete
    r = await http_client.delete(
        f"/v1/orgs/{slug}/watches/{created['id']}",
        headers={"Authorization": f"Bearer {member_jwt}"},
    )
    assert r.status_code == 403

    # admin can
    r = await http_client.delete(
        f"/v1/orgs/{slug}/watches/{created['id']}",
        headers={"Authorization": f"Bearer {admin_jwt}"},
    )
    assert r.status_code == 204

    # subsequent get → 404
    g = await http_client.get(
        f"/v1/orgs/{slug}/watches/{created['id']}",
        headers={"Authorization": f"Bearer {admin_jwt}"},
    )
    assert g.status_code == 404


# ---------------------------------------------------------------------------
# Cross-tenant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_tenant_get_returns_404(
    http_client, org_id, other_org_id, user_factory
) -> None:
    _, jwt_a = await user_factory(org_id, role="owner")
    _, jwt_b = await user_factory(other_org_id, role="owner")
    slug_a = await _slug_of(org_id)

    created_in_a = (
        await http_client.post(
            f"/v1/orgs/{slug_a}/watches",
            json={"url": "https://example.test/secret"},
            headers={"Authorization": f"Bearer {jwt_a}"},
        )
    ).json()

    # User from org B tries to read it via org A's URL — they're not
    # a member of A, so 404.
    r = await http_client.get(
        f"/v1/orgs/{slug_a}/watches/{created_in_a['id']}",
        headers={"Authorization": f"Bearer {jwt_b}"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# API-key auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_key_with_write_scope_can_create(
    http_client, org_id, api_key_factory
) -> None:
    key = await api_key_factory(org_id, scopes=["watches:read", "watches:write"])
    slug = await _slug_of(org_id)
    r = await http_client.post(
        f"/v1/orgs/{slug}/watches",
        json={"url": "https://example.test/by-api"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 201


@pytest.mark.asyncio
async def test_api_key_read_only_cannot_create(
    http_client, org_id, api_key_factory
) -> None:
    key = await api_key_factory(org_id, scopes=["watches:read"])
    slug = await _slug_of(org_id)
    r = await http_client.post(
        f"/v1/orgs/{slug}/watches",
        json={"url": "https://example.test/no"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_api_key_for_wrong_org_is_404(
    http_client, org_id, other_org_id, api_key_factory
) -> None:
    key = await api_key_factory(other_org_id, scopes=["watches:read"])
    slug_a = await _slug_of(org_id)
    r = await http_client.get(
        f"/v1/orgs/{slug_a}/watches",
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Watch ↔ tag assignment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assign_tags_replaces_set(http_client, org_id, user_factory) -> None:
    _, jwt = await user_factory(org_id, role="member")
    slug = await _slug_of(org_id)
    h = {"Authorization": f"Bearer {jwt}"}

    w = (
        await http_client.post(
            f"/v1/orgs/{slug}/watches",
            json={"url": "https://example.test/w"},
            headers=h,
        )
    ).json()
    t1 = (
        await http_client.post(
            f"/v1/orgs/{slug}/tags", json={"name": "t1"}, headers=h
        )
    ).json()
    t2 = (
        await http_client.post(
            f"/v1/orgs/{slug}/tags", json={"name": "t2"}, headers=h
        )
    ).json()

    r = await http_client.put(
        f"/v1/orgs/{slug}/watches/{w['id']}/tags",
        json={"tag_ids": [t1["id"], t2["id"]]},
        headers=h,
    )
    assert r.status_code == 200
    names = {t["name"].lower() for t in r.json()["tags"]}
    assert names == {"t1", "t2"}

    # Replace with empty → no tags.
    r2 = await http_client.put(
        f"/v1/orgs/{slug}/watches/{w['id']}/tags",
        json={"tag_ids": []},
        headers=h,
    )
    assert r2.status_code == 200
    assert r2.json()["tags"] == []


@pytest.mark.asyncio
async def test_assign_unknown_tag_id_is_silently_dropped(
    http_client, org_id, user_factory
) -> None:
    _, jwt = await user_factory(org_id, role="member")
    slug = await _slug_of(org_id)
    h = {"Authorization": f"Bearer {jwt}"}

    w = (
        await http_client.post(
            f"/v1/orgs/{slug}/watches",
            json={"url": "https://example.test/w"},
            headers=h,
        )
    ).json()
    t = (
        await http_client.post(
            f"/v1/orgs/{slug}/tags", json={"name": "real"}, headers=h
        )
    ).json()

    r = await http_client.put(
        f"/v1/orgs/{slug}/watches/{w['id']}/tags",
        json={"tag_ids": [t["id"], str(uuid4())]},
        headers=h,
    )
    assert r.status_code == 200
    # Bogus id silently dropped — only the real tag attached.
    names = {t["name"].lower() for t in r.json()["tags"]}
    assert names == {"real"}
