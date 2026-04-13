"""API-key admin endpoints under ``/v1/orgs/{slug}/api-keys``."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, status

from ..db import with_current_org
from ..models.audit_log import ActorKind
from ..models.membership import MembershipRole
from ..schemas.api_keys import (
    ApiKeyCreate,
    ApiKeyCreateResponse,
    ApiKeyListOut,
    ApiKeyOut,
)
from ..security.deps import MembershipContext, require_membership
from ..services import api_keys as api_keys_svc
from ..services import audit

router = APIRouter(
    prefix="/v1/orgs/{slug}/api-keys",
    tags=["api-keys"],
)

_require_admin = require_membership(MembershipRole.admin)


@router.post(
    "",
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_key(
    body: ApiKeyCreate,
    slug: str = Path(..., pattern=r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$"),
    ctx: MembershipContext = Depends(_require_admin),
) -> ApiKeyCreateResponse:
    scopes = [s.value for s in body.scopes]

    async with with_current_org(ctx.org_id) as db:
        row, plaintext = await api_keys_svc.create(
            db,
            org_id=ctx.org_id,
            name=body.name,
            scopes=scopes,
            created_by_user_id=ctx.user.id,
            expires_at=body.expires_at,
        )
        await audit.record(
            db,
            action="apikey.issue",
            actor_kind=ActorKind.user,
            actor_user_id=ctx.user.id,
            org_id=ctx.org_id,
            target_type="api_key",
            target_id=str(row.id),
            metadata={"name": body.name, "scopes": scopes},
        )
        # Build the response from the flushed row (so id/created_at are
        # populated) and attach the plaintext just this once.
        return ApiKeyCreateResponse(
            **ApiKeyOut.model_validate(row).model_dump(),
            plaintext_key=plaintext,
        )


@router.get("", response_model=ApiKeyListOut)
async def list_api_keys(
    slug: str = Path(..., pattern=r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$"),
    ctx: MembershipContext = Depends(_require_admin),
) -> ApiKeyListOut:
    async with with_current_org(ctx.org_id) as db:
        rows = await api_keys_svc.list_for_org(db, org_id=ctx.org_id)
    return ApiKeyListOut(api_keys=[ApiKeyOut.model_validate(r) for r in rows])


@router.delete("/{api_key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    api_key_id: UUID,
    slug: str = Path(..., pattern=r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$"),
    ctx: MembershipContext = Depends(_require_admin),
) -> None:
    async with with_current_org(ctx.org_id) as db:
        revoked = await api_keys_svc.revoke_by_id(
            db, api_key_id=api_key_id, org_id=ctx.org_id
        )
        if not revoked:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="not found"
            )
        await audit.record(
            db,
            action="apikey.revoke",
            actor_kind=ActorKind.user,
            actor_user_id=ctx.user.id,
            org_id=ctx.org_id,
            target_type="api_key",
            target_id=str(api_key_id),
        )
