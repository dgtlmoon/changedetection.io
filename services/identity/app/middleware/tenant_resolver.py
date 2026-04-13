"""Tenant resolver — maps the inbound request to an organisation.

Resolution order (first match wins):

1. **Subdomain**. Host ``acme.change.sairo.app`` resolves to ``orgs.slug = 'acme'``.
2. **Custom domain**. Host ``watch.acme.com`` looks up a (Phase 5)
   ``custom_domains`` row. *Not implemented yet — stub that always returns None.*
3. **Path fallback**. The path ``/v1/orgs/{slug}/…`` (used by the CLI and
   by services that can't set ``Host:``) reads the slug from the URL.

If none match, the request has no org context. Routes that require a
tenant use the :func:`require_org` dependency; routes that are
public-by-design (signup, ``/me``, login) use :func:`public_route`.

The resolver sets ``request.state.org`` and ``request.state.org_id``.
The database session context manager :func:`app.db.with_current_org`
then issues ``SET LOCAL app.current_org`` so RLS policies apply.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Awaitable, Callable
from uuid import UUID

from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from ..config import Settings, get_settings
from ..db import admin_session
from ..models import Org

# Accepts ``/v1/orgs/<slug>/...`` as the fallback.
_PATH_ORG_RE = re.compile(r"^/v\d+/orgs/(?P<slug>[a-z0-9-]{3,40})(?:/|$)")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")


@dataclass(slots=True, frozen=True)
class ResolvedOrg:
    """Light-weight view of the tenant for use in request.state."""

    id: UUID
    slug: str


class TenantResolverMiddleware(BaseHTTPMiddleware):
    """Resolves the tenant from subdomain / custom domain / path."""

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
            org = await _lookup_org_by_slug(slug)
            if org is not None:
                request.state.org = ResolvedOrg(id=org.id, slug=org.slug)
                request.state.org_id = org.id

        return await call_next(request)

    def _extract_slug(self, request: Request) -> str | None:
        """Try subdomain → custom domain → path. First match wins."""
        # 1. Subdomain.
        host = (request.headers.get("host") or "").split(":")[0].lower()
        root = self._settings.root_domain.lower()
        if host and host.endswith("." + root):
            sub = host[: -len("." + root)]
            # Only the *first* label; deeper subdomains are rejected so
            # we don't accidentally route `foo.bar.change.sairo.app`.
            if "." not in sub and _SLUG_RE.match(sub):
                return sub

        # 2. Custom domain — Phase 5.
        # if custom_domain_lookup(host) is not None: ...

        # 3. Path fallback.
        m = _PATH_ORG_RE.match(request.url.path)
        if m is not None:
            slug = m.group("slug")
            if _SLUG_RE.match(slug):
                return slug

        return None


async def _lookup_org_by_slug(slug: str) -> Org | None:
    """Admin-role lookup; bypasses RLS because we don't know the org yet.

    Kept intentionally narrow — only one query, only one input field.
    """
    async with admin_session() as session:
        result = await session.execute(
            select(Org).where(Org.slug == slug, Org.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()
