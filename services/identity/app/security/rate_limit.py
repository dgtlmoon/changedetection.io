"""Redis-backed sliding-window rate limiter.

Implementation: sorted set per bucket keyed by timestamp. Each request
increments by one; evicts entries older than the window; counts what's
left. O(log N) on the Redis side.

Lua-less — just three `ZREMRANGEBYSCORE` / `ZADD` / `ZCARD` calls in a
pipeline. At the traffic volumes the identity service sees (signup /
login) this is well within budget.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    def now(self) -> float: ...


class SystemClock:
    def now(self) -> float:
        return time.time()


@dataclass(slots=True, frozen=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after: int  # seconds until the oldest counted event expires


class RateLimiter:
    """Fixed-window budget spread over a sliding window.

    Not meant for hot-path high-QPS traffic; identity endpoints are
    signup / login / reset — single-digit QPS per user at worst.
    """

    def __init__(self, redis, clock: Clock | None = None) -> None:
        self._redis = redis
        self._clock = clock or SystemClock()

    async def check(
        self,
        *,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> RateLimitResult:
        now = self._clock.now()
        window_start = now - window_seconds
        bucket = f"rl:{key}"

        pipe = self._redis.pipeline(transaction=True)
        pipe.zremrangebyscore(bucket, 0, window_start)
        pipe.zadd(bucket, {f"{now}:{id(pipe)}": now})
        pipe.zcard(bucket)
        pipe.expire(bucket, window_seconds + 1)
        _, _, count, _ = await pipe.execute()

        count = int(count)
        allowed = count <= limit
        remaining = max(limit - count, 0)

        if allowed:
            return RateLimitResult(
                allowed=True, remaining=remaining, retry_after=0
            )

        # Compute retry_after from the oldest entry in the window.
        oldest = await self._redis.zrange(bucket, 0, 0, withscores=True)
        retry_after = 0
        if oldest:
            _, oldest_ts = oldest[0]
            retry_after = max(1, int(oldest_ts + window_seconds - now))
        return RateLimitResult(
            allowed=False, remaining=0, retry_after=retry_after
        )
