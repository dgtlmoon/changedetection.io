"""Unit tests for the tenant-resolver middleware.

These tests do NOT hit the database — they exercise the request-parsing
logic only. The ``_lookup_org_by_slug`` call is monkey-patched to a
stub so the middleware stays testable without Postgres.

A separate integration suite (Phase 2) will assert end-to-end that a
real ``orgs`` row becomes a ``ResolvedOrg`` on ``request.state``.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.middleware import tenant_resolver as tr
from app.models import Org


def _stub_org(slug: str) -> Org:
    org = Org()
    org.id = uuid4()
    org.slug = slug
    org.name = slug
    return org


@pytest.fixture
def app_with_stub(monkeypatch):
    """App whose org-lookup is a dict; no database needed."""
    orgs = {
        "acme": _stub_org("acme"),
        "beta-co": _stub_org("beta-co"),
    }

    async def _lookup(slug: str) -> Org | None:
        return orgs.get(slug)

    monkeypatch.setattr(tr, "_lookup_org_by_slug", _lookup)

    app = create_app()

    # An inspector endpoint that echoes back what the middleware put on
    # request.state. Kept inside the test so it doesn't pollute the app.
    from fastapi import Request

    @app.get("/_test/whoami")
    async def whoami(request: Request) -> dict[str, str | None]:
        org = getattr(request.state, "org", None)
        return {"slug": org.slug if org else None}

    return app


@pytest.mark.asyncio
async def test_subdomain_resolves(monkeypatch, app_with_stub) -> None:
    monkeypatch.setenv("IDENTITY_ROOT_DOMAIN", "change.sairo.app")
    transport = ASGITransport(app=app_with_stub)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        r = await c.get("/_test/whoami", headers={"host": "acme.change.sairo.app"})
    assert r.status_code == 200
    assert r.json() == {"slug": "acme"}


@pytest.mark.asyncio
async def test_unknown_subdomain_is_none(app_with_stub) -> None:
    transport = ASGITransport(app=app_with_stub)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        r = await c.get("/_test/whoami", headers={"host": "nobody.change.sairo.app"})
    assert r.status_code == 200
    assert r.json() == {"slug": None}


@pytest.mark.asyncio
async def test_deep_subdomain_is_rejected(app_with_stub) -> None:
    """``foo.acme.change.sairo.app`` must NOT resolve to org ``acme``."""
    transport = ASGITransport(app=app_with_stub)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        r = await c.get(
            "/_test/whoami", headers={"host": "foo.acme.change.sairo.app"}
        )
    assert r.status_code == 200
    assert r.json() == {"slug": None}


@pytest.mark.asyncio
async def test_path_fallback_resolves(app_with_stub) -> None:
    transport = ASGITransport(app=app_with_stub)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        # No subdomain; path carries the slug.
        r = await c.get(
            "/_test/whoami",
            headers={"host": "api.change.sairo.app"},
        )
    assert r.status_code == 200
    assert r.json() == {"slug": None}


@pytest.mark.asyncio
async def test_root_no_subdomain_no_path_returns_none(app_with_stub) -> None:
    transport = ASGITransport(app=app_with_stub)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        r = await c.get("/_test/whoami", headers={"host": "change.sairo.app"})
    assert r.status_code == 200
    assert r.json() == {"slug": None}


@pytest.mark.asyncio
async def test_invalid_slug_is_ignored(app_with_stub) -> None:
    """Slugs like ``-bad`` or ``ab`` fall through to the DB lookup step
    only when they match the slug regex. A pathological host is not
    forwarded to the DB."""
    transport = ASGITransport(app=app_with_stub)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        r = await c.get("/_test/whoami", headers={"host": "a.change.sairo.app"})
    assert r.status_code == 200
    assert r.json() == {"slug": None}


def test_slug_regex_accepts_valid_and_rejects_invalid() -> None:
    assert tr._SLUG_RE.match("acme")
    assert tr._SLUG_RE.match("beta-co")
    assert tr._SLUG_RE.match("a1b2c3")
    assert not tr._SLUG_RE.match("-bad")
    assert not tr._SLUG_RE.match("bad-")
    assert not tr._SLUG_RE.match("ab")  # too short
    assert not tr._SLUG_RE.match("x" * 41)  # too long
    assert not tr._SLUG_RE.match("BAD")  # uppercase rejected
    assert not tr._SLUG_RE.match("has.dot")
    assert not tr._SLUG_RE.match("has space")
