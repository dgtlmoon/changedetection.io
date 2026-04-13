"""HTTP integration tests for tag CRUD."""

from __future__ import annotations

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


@pytest.mark.asyncio
async def test_create_then_list(http_client, org_id, user_factory) -> None:
    _, jwt = await user_factory(org_id, role="member")
    slug = await _slug_of(org_id)
    h = {"Authorization": f"Bearer {jwt}"}

    r = await http_client.post(
        f"/v1/orgs/{slug}/tags",
        json={"name": "alerts", "color": "#ff8800"},
        headers=h,
    )
    assert r.status_code == 201
    assert r.json()["color"] == "#ff8800"

    r2 = await http_client.get(f"/v1/orgs/{slug}/tags", headers=h)
    assert r2.status_code == 200
    assert any(t["name"].lower() == "alerts" for t in r2.json()["tags"])


@pytest.mark.asyncio
async def test_create_duplicate_is_409(http_client, org_id, user_factory) -> None:
    _, jwt = await user_factory(org_id, role="member")
    slug = await _slug_of(org_id)
    h = {"Authorization": f"Bearer {jwt}"}

    r1 = await http_client.post(
        f"/v1/orgs/{slug}/tags", json={"name": "dupe"}, headers=h
    )
    assert r1.status_code == 201
    r2 = await http_client.post(
        f"/v1/orgs/{slug}/tags", json={"name": "dupe"}, headers=h
    )
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_invalid_color_is_422(http_client, org_id, user_factory) -> None:
    _, jwt = await user_factory(org_id, role="member")
    slug = await _slug_of(org_id)
    r = await http_client.post(
        f"/v1/orgs/{slug}/tags",
        json={"name": "bad-color", "color": "not-a-hex"},
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_delete_requires_admin(http_client, org_id, user_factory) -> None:
    _, member_jwt = await user_factory(org_id, role="member")
    _, admin_jwt = await user_factory(org_id, role="admin")
    slug = await _slug_of(org_id)

    created = (
        await http_client.post(
            f"/v1/orgs/{slug}/tags",
            json={"name": "del"},
            headers={"Authorization": f"Bearer {member_jwt}"},
        )
    ).json()

    r = await http_client.delete(
        f"/v1/orgs/{slug}/tags/{created['id']}",
        headers={"Authorization": f"Bearer {member_jwt}"},
    )
    assert r.status_code == 403

    r = await http_client.delete(
        f"/v1/orgs/{slug}/tags/{created['id']}",
        headers={"Authorization": f"Bearer {admin_jwt}"},
    )
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_viewer_can_list_but_not_create(
    http_client, org_id, user_factory
) -> None:
    _, viewer_jwt = await user_factory(org_id, role="viewer")
    slug = await _slug_of(org_id)
    h = {"Authorization": f"Bearer {viewer_jwt}"}

    r = await http_client.get(f"/v1/orgs/{slug}/tags", headers=h)
    assert r.status_code == 200

    r = await http_client.post(
        f"/v1/orgs/{slug}/tags", json={"name": "noop"}, headers=h
    )
    assert r.status_code == 403
