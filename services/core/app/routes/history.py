"""Watch-history routes under /v1/orgs/{slug}/watches/{watch_id}/history.

Three endpoints worth flagging:

* ``POST`` accepts a ``multipart/form-data`` upload (so blobs of any
  size travel as a real file, not a base64-blown JSON string). The
  blob is uploaded to the configured object store and the index row
  is written in a single DB transaction. If the blob upload fails the
  DB transaction never commits, so we never get an orphan row.

* ``GET …/content`` streams the blob back. The reverse proxy can
  later be configured to redirect to a presigned URL instead.

* ``DELETE`` removes the DB row first, then the blob — failed blob
  delete leaves a GC-able row rather than a phantom key.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import UUID

import structlog
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Path,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse

from ..db import with_current_org
from ..object_store import ObjectNotFound, build_object_store
from ..schemas.history import HistoryEntryOut, HistoryListOut
from ..security.deps import TenantContext, require_membership
from ..store import PgHistoryStore, PgWatchStore

router = APIRouter(
    prefix="/v1/orgs/{slug}/watches/{watch_id}/history",
    tags=["history"],
)

_SLUG_RE = r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$"

_log = structlog.get_logger()
_history_store = PgHistoryStore()
_watch_store = PgWatchStore()


def _object_key(*, org_id: UUID, watch_id: UUID, kind: str, taken_at: datetime) -> str:
    """Canonical key. Identical scheme to the one in the design doc."""
    folder = {
        "snapshot": "snapshots",
        "screenshot": "screenshots",
        "pdf": "pdfs",
        "browser_step": "browser_steps",
    }.get(kind, kind + "s")
    ts = taken_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f")
    return f"{org_id}/watches/{watch_id}/{folder}/{ts}"


@router.get("", response_model=HistoryListOut)
async def list_history(
    watch_id: UUID,
    slug: str = Path(..., pattern=_SLUG_RE),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    kind: str | None = Query(default=None),
    ctx: TenantContext = Depends(require_membership("viewer")),
) -> HistoryListOut:
    async with with_current_org(ctx.org_id) as db:
        rows = await _history_store.list(
            db,
            org_id=ctx.org_id,
            watch_id=watch_id,
            limit=limit,
            offset=offset,
            kind=kind,
        )
    return HistoryListOut(
        entries=[HistoryEntryOut.model_validate(r) for r in rows],
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=HistoryEntryOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_history_entry(
    watch_id: UUID,
    slug: str = Path(..., pattern=_SLUG_RE),
    kind: str = Form(...),
    content_type: str = Form(...),
    body: UploadFile = File(...),
    ctx: TenantContext = Depends(require_membership("member")),
) -> HistoryEntryOut:
    if kind not in PgHistoryStore.ALLOWED_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown kind {kind!r}",
        )

    payload = await body.read()
    size = len(payload)
    md5 = hashlib.md5(payload, usedforsecurity=False).hexdigest()
    taken_at = datetime.now(timezone.utc)
    object_key = _object_key(
        org_id=ctx.org_id, watch_id=watch_id, kind=kind, taken_at=taken_at
    )

    store = build_object_store()
    # Blob first — if upload fails we haven't dirtied the DB.
    await store.put(object_key, payload, content_type=content_type)

    try:
        async with with_current_org(ctx.org_id) as db:
            row = await _history_store.record(
                db,
                org_id=ctx.org_id,
                watch_id=watch_id,
                taken_at=taken_at,
                kind=kind,
                content_type=content_type,
                object_key=object_key,
                size_bytes=size,
                hash_md5=md5,
            )
    except Exception:
        # Roll back the blob on DB failure so we don't accumulate
        # orphans. Best-effort — don't shadow the original exception.
        try:
            await store.delete(object_key)
        except Exception:  # noqa: BLE001
            _log.warning("history.upload.blob_rollback_failed", key=object_key)
        raise

    return HistoryEntryOut.model_validate(row)


@router.get("/{entry_id}/content")
async def get_history_content(
    watch_id: UUID,
    entry_id: UUID,
    slug: str = Path(..., pattern=_SLUG_RE),
    ctx: TenantContext = Depends(require_membership("viewer")),
) -> Response:
    async with with_current_org(ctx.org_id) as db:
        row = await _history_store.get(
            db, org_id=ctx.org_id, watch_id=watch_id, entry_id=entry_id
        )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")

    store = build_object_store()
    try:
        body = await store.get(row.object_key)
    except ObjectNotFound:
        # Index row exists but blob is gone — return 410 Gone so the
        # client can distinguish from "wrong id".
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="content no longer available",
        ) from None

    headers = {
        "Content-Length": str(len(body)),
        "ETag": f'"{row.hash_md5}"',
    }
    return Response(content=body, media_type=row.content_type, headers=headers)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_history_entry(
    watch_id: UUID,
    entry_id: UUID,
    background: BackgroundTasks,
    slug: str = Path(..., pattern=_SLUG_RE),
    ctx: TenantContext = Depends(require_membership("admin")),
) -> None:
    async with with_current_org(ctx.org_id) as db:
        deleted, key = await _history_store.delete(
            db, org_id=ctx.org_id, watch_id=watch_id, entry_id=entry_id
        )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")

    # Best-effort blob delete after the DB row is gone. If this fails
    # the row is already gone — we log + leave the blob for a future
    # GC sweep (tracked under Phase 4 ops surface).
    if key is not None:
        async def _drop() -> None:
            store = build_object_store()
            try:
                await store.delete(key)
            except ObjectNotFound:
                pass
            except Exception:  # noqa: BLE001
                _log.warning("history.delete.blob_orphan", key=key)

        background.add_task(_drop)
