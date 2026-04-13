"""Liveness probe — runs without a database."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_healthz_returns_ok(client) -> None:
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_root_returns_service_identity(client) -> None:
    resp = await client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "identity"
    assert "version" in body
