"""Lazy async Redis connection factory.

Uses redis-py's asyncio client (``redis.asyncio``). A single pooled
client is created on first use and reused for the life of the process.

Test code can monkey-patch ``_client`` with a fake (e.g. ``fakeredis``).
"""

from __future__ import annotations

from redis.asyncio import Redis, from_url

from .config import get_settings

_client: Redis | None = None


def get_redis() -> Redis:
    """Return the process-wide Redis client, creating it if needed."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            health_check_interval=30,
        )
    return _client


async def close_redis() -> None:
    """Close the Redis client if it was created. Called from app shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
