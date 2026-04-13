"""Security-headers middleware.

Applied to every response. Values are deliberately strict for an API
surface (no same-origin HTML embeds, no third-party script sources,
no sensor permissions). The marketing site + Next.js app will relax a
subset of these via their own layer.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_STATIC_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-site",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add a fixed set of security headers to every response.

    ``Strict-Transport-Security`` is only set when the request came in
    over HTTPS — emitting HSTS on plain HTTP is ineffective and
    confuses local-dev browsers.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        for k, v in _STATIC_HEADERS.items():
            response.headers.setdefault(k, v)

        scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
        if scheme == "https":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains; preload",
            )
        return response
