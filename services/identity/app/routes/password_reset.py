"""Password reset: request + confirm.

``/request`` ALWAYS returns 204, whether or not the email is known. No
enumeration. The email is only sent if the user exists.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from ..config import get_settings
from ..db import admin_session
from ..email import EmailMessage, build_sender, render_template
from ..models.audit_log import ActorKind
from ..security.rate_limit_dep import rate_limit
from ..services import audit, password_reset, users as users_svc
from ..services.password_reset import ResetError

router = APIRouter(prefix="/v1/auth/password-reset", tags=["auth"])


class RequestBody(BaseModel):
    email: EmailStr


class ConfirmBody(BaseModel):
    token: str = Field(min_length=16, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


@router.post(
    "/request",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit("password-reset-request", 3, 3600, key_per="ip"))],
)
async def request_reset(
    body: RequestBody, background: BackgroundTasks, request: Request
) -> None:
    async with admin_session() as db:
        user = await users_svc.find_by_email(db, body.email)
        if user is None or user.password_hash is None:
            # SSO-only users have no password to reset. Still respond 204.
            # Audit the miss so we can spot enumeration scans in logs.
            await audit.record(
                db,
                action="user.password_reset.request.miss",
                actor_kind=ActorKind.system,
                metadata={"email": body.email},
            )
            return

        token = await password_reset.issue(db, user_id=user.id)
        await audit.record(
            db,
            action="user.password_reset.request",
            actor_kind=ActorKind.user,
            actor_user_id=user.id,
        )

    settings = get_settings()
    reset_url = (
        f"https://{settings.root_domain}/password-reset?token={quote(token)}"
    )
    rendered = render_template(
        "password-reset",
        display_name=user.display_name,
        reset_url=reset_url,
    )
    sender = build_sender()
    background.add_task(
        sender.send,
        EmailMessage(
            to=user.email,
            subject=rendered.subject,
            text_body=rendered.text_body,
            html_body=rendered.html_body,
            tag="password-reset",
        ),
    )


@router.post("/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_reset(body: ConfirmBody) -> None:
    async with admin_session() as db:
        try:
            user = await password_reset.confirm(
                db, token=body.token, new_password=body.new_password
            )
        except ResetError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid or expired token",
            ) from None

        await audit.record(
            db,
            action="user.password_reset.confirm",
            actor_kind=ActorKind.user,
            actor_user_id=user.id,
        )
