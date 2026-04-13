"""HTTP integration tests for watch history (upload + fetch + delete)."""

from __future__ import annotations

import io

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


async def _make_watch(client, slug: str, jwt: str) -> dict:
    r = await client.post(
        f"/v1/orgs/{slug}/watches",
        json={"url": "https://example.test/page"},
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Upload + fetch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_then_list_then_fetch(
    http_client, org_id, user_factory
) -> None:
    _, jwt = await user_factory(org_id, role="member")
    slug = await _slug_of(org_id)
    w = await _make_watch(http_client, slug, jwt)

    body = b"hello world snapshot"
    r = await http_client.post(
        f"/v1/orgs/{slug}/watches/{w['id']}/history",
        files={"body": ("snap.txt", io.BytesIO(body), "text/plain")},
        data={"kind": "snapshot", "content_type": "text/plain"},
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert r.status_code == 201, r.text
    entry = r.json()
    assert entry["kind"] == "snapshot"
    assert entry["size_bytes"] == len(body)

    listing = await http_client.get(
        f"/v1/orgs/{slug}/watches/{w['id']}/history",
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert listing.status_code == 200
    assert any(e["id"] == entry["id"] for e in listing.json()["entries"])

    fetched = await http_client.get(
        f"/v1/orgs/{slug}/watches/{w['id']}/history/{entry['id']}/content",
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert fetched.status_code == 200
    assert fetched.content == body
    assert fetched.headers["content-type"].startswith("text/plain")


@pytest.mark.asyncio
async def test_upload_unknown_kind_is_400(
    http_client, org_id, user_factory
) -> None:
    _, jwt = await user_factory(org_id, role="member")
    slug = await _slug_of(org_id)
    w = await _make_watch(http_client, slug, jwt)
    r = await http_client.post(
        f"/v1/orgs/{slug}/watches/{w['id']}/history",
        files={"body": ("x", io.BytesIO(b"x"), "text/plain")},
        data={"kind": "bogus", "content_type": "text/plain"},
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_requires_admin(http_client, org_id, user_factory) -> None:
    _, member_jwt = await user_factory(org_id, role="member")
    _, admin_jwt = await user_factory(org_id, role="admin")
    slug = await _slug_of(org_id)
    w = await _make_watch(http_client, slug, member_jwt)

    entry = (
        await http_client.post(
            f"/v1/orgs/{slug}/watches/{w['id']}/history",
            files={"body": ("x", io.BytesIO(b"hi"), "text/plain")},
            data={"kind": "snapshot", "content_type": "text/plain"},
            headers={"Authorization": f"Bearer {member_jwt}"},
        )
    ).json()

    r = await http_client.delete(
        f"/v1/orgs/{slug}/watches/{w['id']}/history/{entry['id']}",
        headers={"Authorization": f"Bearer {member_jwt}"},
    )
    assert r.status_code == 403

    r = await http_client.delete(
        f"/v1/orgs/{slug}/watches/{w['id']}/history/{entry['id']}",
        headers={"Authorization": f"Bearer {admin_jwt}"},
    )
    assert r.status_code == 204

    # Subsequent fetch → 404 (DB row gone)
    r = await http_client.get(
        f"/v1/orgs/{slug}/watches/{w['id']}/history/{entry['id']}/content",
        headers={"Authorization": f"Bearer {admin_jwt}"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Cross-tenant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_tenant_history_list_is_404(
    http_client, org_id, other_org_id, user_factory
) -> None:
    _, jwt_a = await user_factory(org_id, role="owner")
    _, jwt_b = await user_factory(other_org_id, role="owner")
    slug_a = await _slug_of(org_id)
    w = await _make_watch(http_client, slug_a, jwt_a)

    r = await http_client.get(
        f"/v1/orgs/{slug_a}/watches/{w['id']}/history",
        headers={"Authorization": f"Bearer {jwt_b}"},
    )
    # B has no membership in A → 404 from require_membership.
    assert r.status_code == 404
