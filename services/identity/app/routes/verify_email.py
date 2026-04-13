"""Email verification: request + confirm."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..config import get_settings
from ..db import admin_session
from ..email import EmailMessage, build_sender, render_template
from ..models.audit_log import ActorKind
from ..security.deps import CurrentUser, get_current_user
from ..security.rate_limit_dep import rate_limit
from ..services import audit, email_verification
from ..services.email_verification import VerificationError

router = APIRouter(prefix="/v1/auth/verify-email", tags=["auth"])


class ConfirmBody(BaseModel):
    token: str = Field(min_length=16, max_length=256)


class ConfirmResponse(BaseModel):
    verified_at: datetime


@router.post(
    "/request",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit("verify-email-request", 5, 3600, key_per="user"))],
)
async def request_verification(
    background: BackgroundTasks,
    current: CurrentUser = Depends(get_current_user),
) -> None:
    """Issue a verification token and mail it to the current user."""
    if current.user.email_verified_at is not None:
        # Already verified. Return 204 so the caller can't probe for
        # account state.
        return

    async with admin_session() as db:
        token = await email_verification.issue(db, user_id=current.id)
        await audit.record(
            db,
            action="user.verify_email.request",
            actor_kind=ActorKind.user,
            actor_user_id=current.id,
        )

    settings = get_settings()
    verify_url = (
        f"https://{settings.root_domain}/verify-email?token={quote(token)}"
    )

    rendered = render_template(
        "verify-email",
        display_name=current.user.display_name,
        verify_url=verify_url,
    )
    sender = build_sender()
    background.add_task(
        sender.send,
        EmailMessage(
            to=current.user.email,
            subject=rendered.subject,
            text_body=rendered.text_body,
            html_body=rendered.html_body,
            tag="verify-email",
        ),
    )


@router.post("/confirm", response_model=ConfirmResponse)
async def confirm_verification(body: ConfirmBody, request: Request) -> ConfirmResponse:
    async with admin_session() as db:
        try:
            user = await email_verification.confirm(db, token=body.token)
        except VerificationError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid or expired token",
            ) from None

        await audit.record(
            db,
            action="user.verify_email.confirm",
            actor_kind=ActorKind.user,
            actor_user_id=user.id,
        )
        # ``email_verified_at`` set by the service; narrow the type.
        assert user.email_verified_at is not None
        return ConfirmResponse(verified_at=user.email_verified_at)
