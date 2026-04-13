"""Invite admin endpoints (nested under ``/v1/orgs/{slug}``)."""

from __future__ import annotations

from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Request, status

from ..config import get_settings
from ..db import admin_session, with_current_org
from ..email import EmailMessage, build_sender, render_template
from ..models.audit_log import ActorKind
from ..models.membership import MembershipRole
from ..schemas.invites import InviteCreate, InviteListOut, InviteOut
from ..security.deps import MembershipContext, require_membership
from ..services import audit, invites as invites_svc
from ..services import users as users_svc

# The ``{slug}`` is consumed by the tenant-resolver middleware, which
# populates ``request.state.org_id``. We still declare it here so
# FastAPI generates the OpenAPI parameter and renders a useful docs
# page.
router = APIRouter(
    prefix="/v1/orgs/{slug}/invites",
    tags=["invites"],
)

# Invite-admin is gated on admin or higher.
_require_admin = require_membership(MembershipRole.admin)


def _org_name_fallback(slug: str) -> str:
    """Safe-ish display name for the invite email when the org row
    isn't attached to the membership lookup."""
    return slug.replace("-", " ").title()


@router.post(
    "",
    response_model=InviteOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_invite(
    body: InviteCreate,
    background: BackgroundTasks,
    slug: str = Path(..., pattern=r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$"),
    ctx: MembershipContext = Depends(_require_admin),
) -> InviteOut:
    if body.role == MembershipRole.owner:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="owner role cannot be granted via invite",
        )

    # Do the tenant-scoped write under RLS.
    async with with_current_org(ctx.org_id) as db:
        row, token = await invites_svc.create(
            db,
            org_id=ctx.org_id,
            email=body.email,
            role=body.role,
            invited_by_user_id=ctx.user.id,
        )
        await audit.record(
            db,
            action="invite.create",
            actor_kind=ActorKind.user,
            actor_user_id=ctx.user.id,
            org_id=ctx.org_id,
            target_type="invite",
            target_id=str(row.id),
            metadata={"email": body.email, "role": body.role.value},
        )
        out = InviteOut.model_validate(row)

    settings = get_settings()
    accept_url = (
        f"https://{settings.root_domain}/invites/accept?token={quote(token)}"
    )
    rendered = render_template(
        "invite",
        org_name=_org_name_fallback(slug),
        inviter_name=ctx.user.user.display_name,
        role=body.role.value,
        accept_url=accept_url,
    )
    sender = build_sender()
    background.add_task(
        sender.send,
        EmailMessage(
            to=body.email,
            subject=rendered.subject,
            text_body=rendered.text_body,
            html_body=rendered.html_body,
            tag="invite",
        ),
    )
    return out


@router.get("", response_model=InviteListOut)
async def list_invites(
    slug: str = Path(..., pattern=r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$"),
    ctx: MembershipContext = Depends(_require_admin),
) -> InviteListOut:
    async with with_current_org(ctx.org_id) as db:
        rows = await invites_svc.list_for_org(db, org_id=ctx.org_id)
    return InviteListOut(invites=[InviteOut.model_validate(r) for r in rows])


@router.delete("/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(
    invite_id: UUID,
    slug: str = Path(..., pattern=r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$"),
    ctx: MembershipContext = Depends(_require_admin),
) -> None:
    async with with_current_org(ctx.org_id) as db:
        deleted = await invites_svc.delete_by_id(
            db, invite_id=invite_id, org_id=ctx.org_id
        )
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="not found"
            )
        await audit.record(
            db,
            action="invite.revoke",
            actor_kind=ActorKind.user,
            actor_user_id=ctx.user.id,
            org_id=ctx.org_id,
            target_type="invite",
            target_id=str(invite_id),
        )
