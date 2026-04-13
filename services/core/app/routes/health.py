"""Liveness + readiness probes."""

from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from ..db import engine

router = APIRouter(tags=["health"])


@router.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
async def readyz() -> JSONResponse:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            {"status": "unready", "reason": type(exc).__name__},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return JSONResponse({"status": "ready"})
