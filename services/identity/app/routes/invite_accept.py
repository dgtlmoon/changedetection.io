"""POST /v1/auth/invites/accept — acceptor-side invite endpoint.

Handles three cases (design: phase-02 § 2c):

  a) Authenticated + email matches invite → attach membership.
  b) Anonymous + existing user for that email → authenticate by
     password, attach membership.
  c) Anonymous + no user yet → create user, attach membership.

All three return a fresh session.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..db import admin_session
from ..models.audit_log import ActorKind
from ..schemas.auth import OrgOut, UserOut
from ..schemas.invites import InviteAcceptRequest, InviteAcceptResponse
from ..security import tokens
from ..security.deps import CurrentUser, get_current_user_optional
from ..security.rate_limit_dep import rate_limit
from ..services import audit, invites as invites_svc, sessions as sessions_svc, users as users_svc
from ..services.errors import EmailAlreadyRegistered, InvalidCredentials

router = APIRouter(prefix="/v1/auth/invites", tags=["auth"])


def _client_info(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    return ua, ip


@router.post(
    "/accept",
    response_model=InviteAcceptResponse,
    dependencies=[Depends(rate_limit("invite-accept", 10, 3600, key_per="ip"))],
)
async def accept_invite(
    body: InviteAcceptRequest,
    request: Request,
    caller: CurrentUser | None = Depends(get_current_user_optional),
) -> InviteAcceptResponse:
    user_agent, ip = _client_info(request)

    async with admin_session() as db:
        pair = await invites_svc.find_pending_by_token(db, token=body.token)
        if pair is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid or expired token",
            )
        invite, org = pair

        # Resolve or create the accepting user.
        user = None
        if caller is not None:
            # (a) Authenticated — caller's email must match the invite.
            if caller.user.email.lower() != invite.email.lower():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="invite email does not match current user",
                )
            user = caller.user
        else:
            existing = await users_svc.find_by_email(db, invite.email)
            if existing is not None:
                # (b) Existing user — require password.
                if not body.password:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="password required",
                    )
                try:
                    user = await users_svc.authenticate(
                        db, email=invite.email, password=body.password
                    )
                except InvalidCredentials:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="invalid credentials",
                    ) from None
            else:
                # (c) New user — require password, create.
                if not body.password:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="password required to create account",
                    )
                try:
                    user = await users_svc.create(
                        db,
                        email=invite.email,
                        password=body.password,
                        display_name=body.display_name,
                    )
                except EmailAlreadyRegistered:
                    # Race: another signup slipped in between our lookup
                    # and the insert. Treat as auth-required.
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="account already exists — please log in",
                    ) from None

        membership = await invites_svc.consume(db, invite=invite, user=user)

        session_row, refresh_plain = await sessions_svc.issue(
            db, user_id=user.id, user_agent=user_agent, ip_address=ip
        )

        await audit.record(
            db,
            action="invite.accept",
            actor_kind=ActorKind.user,
            actor_user_id=user.id,
            org_id=invite.org_id,
            target_type="invite",
            target_id=str(invite.id),
            metadata={"role": membership.role.value},
            ip_address=ip,
            user_agent=user_agent,
        )

        access, access_ttl = tokens.issue_access_token(
            user_id=user.id, session_id=session_row.id
        )

        return InviteAcceptResponse(
            access_token=access,
            refresh_token=refresh_plain,
            access_expires_in=access_ttl,
            user=UserOut.model_validate(user),
            org=OrgOut.model_validate(org),
            role=membership.role.value,
        )
