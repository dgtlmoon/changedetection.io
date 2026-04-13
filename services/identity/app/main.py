"""FastAPI application entry point for the identity service.

This file is intentionally small. Phase 1 only wires:
    - health probes,
    - the tenant resolver middleware.

Phase 2 and onwards hang auth and org-management routes off this same
app.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import FastAPI
from starlette.responses import JSONResponse

from .config import get_settings
from .middleware.security_headers import SecurityHeadersMiddleware
from .middleware.tenant_resolver import TenantResolverMiddleware
from .redis_client import close_redis
from .routes import auth, health, invite_accept, invites, me, password_reset, verify_email

_log = structlog.get_logger()


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    _log.info(
        "identity.startup",
        environment=settings.environment,
        root_domain=settings.root_domain,
        email_backend=settings.email_backend,
    )
    yield
    await close_redis()
    _log.info("identity.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="onChange by Sairo — Identity",
        version="0.1.0",
        description=(
            "Orgs, users, memberships, sessions, API keys. Phase 1 ships the "
            "tenancy primitives only; auth endpoints follow in Phase 2."
        ),
        lifespan=_lifespan,
        # Hide docs in production; devs can hit `/docs` locally.
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
    )

    # Order matters: outermost first. Security headers wrap everything;
    # the tenant resolver is the next layer in.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(TenantResolverMiddleware, settings=settings)

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(me.router)
    app.include_router(verify_email.router)
    app.include_router(password_reset.router)
    app.include_router(invites.router)
    app.include_router(invite_accept.router)

    @app.get("/", include_in_schema=False)
    async def root() -> JSONResponse:
        return JSONResponse({"service": "identity", "version": "0.1.0"})

    return app


app = create_app()
