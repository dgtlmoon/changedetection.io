"""FastAPI application entry point for the core service."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import FastAPI
from starlette.responses import JSONResponse

from .config import get_settings
from .middleware.security_headers import SecurityHeadersMiddleware
from .middleware.tenant_resolver import TenantResolverMiddleware
from .routes import health, history, tags, watches

_log = structlog.get_logger()


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    _log.info(
        "core.startup",
        environment=settings.environment,
        root_domain=settings.root_domain,
        object_store_backend=settings.object_store_backend,
    )
    yield
    _log.info("core.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="onChange by Sairo — Core",
        version="0.1.0",
        description=(
            "Tenant-scoped watch + tag + history API. Authenticates against "
            "the identity service via shared JWT secret_key + the api_keys "
            "table (read-only)."
        ),
        lifespan=_lifespan,
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
    )

    # Outer-most first.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(TenantResolverMiddleware, settings=settings)

    app.include_router(health.router)
    app.include_router(watches.router)
    app.include_router(tags.router)
    app.include_router(history.router)

    @app.get("/", include_in_schema=False)
    async def root() -> JSONResponse:
        return JSONResponse({"service": "core", "version": "0.1.0"})

    return app


app = create_app()
