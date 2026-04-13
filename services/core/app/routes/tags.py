"""Tag CRUD routes under /v1/orgs/{slug}/tags."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, status

from ..db import with_current_org
from ..schemas.tags import TagCreate, TagListOut, TagOut
from ..security.deps import TenantContext, require_membership
from ..store import PgTagStore
from ..store.pg import DuplicateTagName

router = APIRouter(prefix="/v1/orgs/{slug}/tags", tags=["tags"])

_SLUG_RE = r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$"

_tag_store = PgTagStore()


@router.get("", response_model=TagListOut)
async def list_tags(
    slug: str = Path(..., pattern=_SLUG_RE),
    ctx: TenantContext = Depends(require_membership("viewer")),
) -> TagListOut:
    async with with_current_org(ctx.org_id) as db:
        rows = await _tag_store.list(db, org_id=ctx.org_id)
    return TagListOut(tags=[TagOut.model_validate(r) for r in rows])


@router.post("", response_model=TagOut, status_code=status.HTTP_201_CREATED)
async def create_tag(
    body: TagCreate,
    slug: str = Path(..., pattern=_SLUG_RE),
    ctx: TenantContext = Depends(require_membership("member")),
) -> TagOut:
    async with with_current_org(ctx.org_id) as db:
        try:
            row = await _tag_store.create(
                db,
                org_id=ctx.org_id,
                name=body.name,
                color=body.color,
                settings=body.settings,
            )
        except DuplicateTagName:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="tag name already exists in this org",
            ) from None
    return TagOut.model_validate(row)


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    tag_id: UUID,
    slug: str = Path(..., pattern=_SLUG_RE),
    ctx: TenantContext = Depends(require_membership("admin")),
) -> None:
    async with with_current_org(ctx.org_id) as db:
        ok = await _tag_store.delete(db, org_id=ctx.org_id, tag_id=tag_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
