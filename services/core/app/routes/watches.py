"""Watch CRUD routes under /v1/orgs/{slug}/watches."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from ..db import with_current_org
from ..schemas.tags import TagAssignRequest, TagAssignResponse, TagOut
from ..schemas.watches import WatchCreate, WatchListOut, WatchOut, WatchPatchIn
from ..security.deps import TenantContext, require_membership
from ..store import PgTagStore, PgWatchStore

router = APIRouter(
    prefix="/v1/orgs/{slug}/watches",
    tags=["watches"],
)

_SLUG_RE = r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$"

_watch_store = PgWatchStore()
_tag_store = PgTagStore()


@router.get("", response_model=WatchListOut)
async def list_watches(
    slug: str = Path(..., pattern=_SLUG_RE),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    paused: bool | None = Query(default=None),
    tag_id: UUID | None = Query(default=None),
    ctx: TenantContext = Depends(require_membership("viewer")),
) -> WatchListOut:
    async with with_current_org(ctx.org_id) as db:
        rows = await _watch_store.list(
            db,
            org_id=ctx.org_id,
            limit=limit,
            offset=offset,
            paused=paused,
            tag_id=tag_id,
        )
    return WatchListOut(
        watches=[WatchOut.model_validate(r) for r in rows],
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=WatchOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_watch(
    body: WatchCreate,
    slug: str = Path(..., pattern=_SLUG_RE),
    ctx: TenantContext = Depends(require_membership("member")),
) -> WatchOut:
    async with with_current_org(ctx.org_id) as db:
        row = await _watch_store.create(
            db,
            org_id=ctx.org_id,
            url=str(body.url),
            title=body.title,
            processor=body.processor,
            fetch_backend=body.fetch_backend,
            time_between_check_seconds=body.time_between_check_seconds,
            settings=body.settings,
        )
    return WatchOut.model_validate(row)


@router.get("/{watch_id}", response_model=WatchOut)
async def get_watch(
    watch_id: UUID,
    slug: str = Path(..., pattern=_SLUG_RE),
    ctx: TenantContext = Depends(require_membership("viewer")),
) -> WatchOut:
    async with with_current_org(ctx.org_id) as db:
        row = await _watch_store.get(db, org_id=ctx.org_id, watch_id=watch_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return WatchOut.model_validate(row)


@router.patch("/{watch_id}", response_model=WatchOut)
async def update_watch(
    watch_id: UUID,
    body: WatchPatchIn,
    slug: str = Path(..., pattern=_SLUG_RE),
    ctx: TenantContext = Depends(require_membership("member")),
) -> WatchOut:
    # pydantic's ``model_dump(exclude_unset=True)`` drops keys the
    # caller didn't supply, so ``{title: null}`` clears and an absent
    # key leaves the field untouched.
    patch = body.model_dump(exclude_unset=True)
    if "url" in patch and patch["url"] is not None:
        patch["url"] = str(patch["url"])

    async with with_current_org(ctx.org_id) as db:
        row = await _watch_store.update(
            db, org_id=ctx.org_id, watch_id=watch_id, patch=patch
        )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return WatchOut.model_validate(row)


@router.delete("/{watch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watch(
    watch_id: UUID,
    slug: str = Path(..., pattern=_SLUG_RE),
    ctx: TenantContext = Depends(require_membership("admin")),
) -> None:
    async with with_current_org(ctx.org_id) as db:
        ok = await _watch_store.delete(db, org_id=ctx.org_id, watch_id=watch_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")


# ---------------------------------------------------------------------------
# Watch ↔ tag assignment
# ---------------------------------------------------------------------------


@router.get("/{watch_id}/tags", response_model=TagAssignResponse)
async def list_watch_tags(
    watch_id: UUID,
    slug: str = Path(..., pattern=_SLUG_RE),
    ctx: TenantContext = Depends(require_membership("viewer")),
) -> TagAssignResponse:
    from sqlalchemy import select

    from ..models import WatchTag, WatchTagLink

    async with with_current_org(ctx.org_id) as db:
        w = await _watch_store.get(db, org_id=ctx.org_id, watch_id=watch_id)
        if w is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="not found"
            )
        result = await db.execute(
            select(WatchTag)
            .join(WatchTagLink, WatchTagLink.tag_id == WatchTag.id)
            .where(
                WatchTagLink.watch_id == watch_id,
                WatchTag.org_id == ctx.org_id,
                WatchTag.deleted_at.is_(None),
            )
            .order_by(WatchTag.name)
        )
        tags = list(result.scalars().all())
    return TagAssignResponse(tags=[TagOut.model_validate(t) for t in tags])


@router.put("/{watch_id}/tags", response_model=TagAssignResponse)
async def replace_watch_tags(
    watch_id: UUID,
    body: TagAssignRequest,
    slug: str = Path(..., pattern=_SLUG_RE),
    ctx: TenantContext = Depends(require_membership("member")),
) -> TagAssignResponse:
    async with with_current_org(ctx.org_id) as db:
        # Confirm watch exists before wasting a round-trip.
        w = await _watch_store.get(db, org_id=ctx.org_id, watch_id=watch_id)
        if w is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="not found"
            )
        final = await _tag_store.assign_to_watch(
            db,
            org_id=ctx.org_id,
            watch_id=watch_id,
            tag_ids=body.tag_ids,
        )
    return TagAssignResponse(tags=[TagOut.model_validate(t) for t in final])
