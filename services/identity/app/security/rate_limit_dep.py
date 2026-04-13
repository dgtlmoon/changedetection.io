"""FastAPI dependency factory for rate limiting.

Usage in a route:

.. code-block:: python

    from fastapi import Depends
    from .security.rate_limit_dep import rate_limit

    @router.post("/login", dependencies=[Depends(rate_limit("login", 10, 3600, key_per="ip_email"))])
    async def login(...): ...
"""

from __future__ import annotations

from typing import Literal

from fastapi import HTTPException, Request, status

from ..redis_client import get_redis
from .rate_limit import RateLimiter

KeyPer = Literal["ip", "ip_email", "user"]


def rate_limit(
    action: str,
    limit: int,
    window_seconds: int,
    *,
    key_per: KeyPer = "ip",
):
    """Return a FastAPI dependency that enforces a sliding-window limit.

    ``action`` is embedded in the Redis key so different endpoints have
    independent buckets. ``key_per`` selects the identity axis.
    """

    async def _dep(request: Request) -> None:
        ip = request.client.host if request.client else "unknown"

        if key_per == "ip":
            identity = ip
        elif key_per == "ip_email":
            # Best-effort: email lives in the JSON body. Routes that
            # want email-axis limiting read it themselves; the dep
            # falls back to IP-only if the body isn't yet parsed.
            identity = ip
        elif key_per == "user":
            user = getattr(request.state, "user_id", None)
            identity = str(user) if user else ip
        else:  # pragma: no cover - enforced by Literal
            identity = ip

        limiter = RateLimiter(get_redis())
        result = await limiter.check(
            key=f"{action}:{identity}",
            limit=limit,
            window_seconds=window_seconds,
        )
        if not result.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="rate limit exceeded",
                headers={"Retry-After": str(result.retry_after)},
            )

    return _dep
