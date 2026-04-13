"""Sliding-window rate limiter tests (no real Redis)."""

from __future__ import annotations

import pytest
import fakeredis.aioredis

from app.security.rate_limit import Clock, RateLimiter


class _FakeClock:
    """Manually advanced clock for deterministic tests."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self._t = start

    def now(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


@pytest.fixture
def redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.mark.asyncio
async def test_under_limit_always_allows(redis) -> None:
    clock = _FakeClock()
    lim = RateLimiter(redis, clock=clock)
    for _ in range(5):
        r = await lim.check(key="k", limit=5, window_seconds=60)
        assert r.allowed is True


@pytest.mark.asyncio
async def test_sixth_request_is_blocked(redis) -> None:
    clock = _FakeClock()
    lim = RateLimiter(redis, clock=clock)
    for _ in range(5):
        await lim.check(key="k2", limit=5, window_seconds=60)
    r = await lim.check(key="k2", limit=5, window_seconds=60)
    assert r.allowed is False
    assert r.retry_after >= 1
    assert r.remaining == 0


@pytest.mark.asyncio
async def test_window_slides(redis) -> None:
    clock = _FakeClock()
    lim = RateLimiter(redis, clock=clock)
    for _ in range(5):
        await lim.check(key="k3", limit=5, window_seconds=60)
    # Advance past the window — oldest entry ages out.
    clock.advance(61)
    r = await lim.check(key="k3", limit=5, window_seconds=60)
    assert r.allowed is True


@pytest.mark.asyncio
async def test_different_keys_are_independent(redis) -> None:
    clock = _FakeClock()
    lim = RateLimiter(redis, clock=clock)
    for _ in range(5):
        await lim.check(key="alice", limit=5, window_seconds=60)
    r = await lim.check(key="bob", limit=5, window_seconds=60)
    assert r.allowed is True
