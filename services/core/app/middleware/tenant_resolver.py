"""Tenant resolver — subdomain + path fallback.

Mirrors the identity service's resolver. Reads the ``orgs`` table via
raw SQL (``security.identity_reads``) so the coupling is explicit —
when we extract ``packages/shared/identity-client/`` this imports
from there.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Awaitable, Callable
from uuid import UUID

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from ..config import Settings, get_settings
from ..db import admin_session
from ..security.identity_reads import resolve_org_by_slug

_PATH_ORG_RE = re.compile(r"^/v\d+/orgs/(?P<slug>[a-z0-9-]{3,40})(?:/|$)")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")


@dataclass(slots=True, frozen=True)
class ResolvedOrg:
    id: UUID
    slug: str


class TenantResolverMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, settings: Settings | None = None) -> None:
        super().__init__(app)
        self._settings = settings or get_settings()

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.org = None
        request.state.org_id = None

        slug = self._extract_slug(request)
        if slug is not None:
            async with admin_session() as db:
                hit = await resolve_org_by_slug(db, slug)
            if hit is not None:
                org_id, resolved_slug = hit
                request.state.org = ResolvedOrg(id=org_id, slug=resolved_slug)
                request.state.org_id = org_id

        return await call_next(request)

    def _extract_slug(self, request: Request) -> str | None:
        host = (request.headers.get("host") or "").split(":")[0].lower()
        root = self._settings.root_domain.lower()
        if host and host.endswith("." + root):
            sub = host[: -len("." + root)]
            if "." not in sub and _SLUG_RE.match(sub):
                return sub

        m = _PATH_ORG_RE.match(request.url.path)
        if m is not None:
            slug = m.group("slug")
            if _SLUG_RE.match(slug):
                return slug

        return None
