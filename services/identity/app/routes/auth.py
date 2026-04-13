"""Phase-2a auth endpoints: signup, login, refresh, logout."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError

from ..db import admin_session
from ..models.audit_log import ActorKind
from ..schemas.auth import (
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    SignupRequest,
    SignupResponse,
    TokenBundle,
    UserOut,
    OrgOut,
)
from ..security import tokens
from ..security.deps import CurrentUser, get_current_user
from ..services import audit, orgs as orgs_svc, sessions as sessions_svc, users as users_svc
from ..services.errors import (
    EmailAlreadyRegistered,
    InvalidCredentials,
    SessionNotFound,
    SessionReuseDetected,
    SlugUnavailable,
)

router = APIRouter(prefix="/v1/auth", tags=["auth"])


def _client_info(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    return ua, ip


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_201_CREATED,
)
async def signup(body: SignupRequest, request: Request) -> SignupResponse:
    user_agent, ip = _client_info(request)
    async with admin_session() as db:
        try:
            user = await users_svc.create(
                db,
                email=body.email,
                password=body.password,
                display_name=body.display_name,
            )
        except EmailAlreadyRegistered:
            # We DO return 409 here (not a generic 401) because the
            # email address the caller just typed is their own. There's
            # no enumeration risk.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="email already registered",
            ) from None

        try:
            org = await orgs_svc.create_with_owner(
                db, name=body.org_name, slug=body.org_slug, owner=user
            )
        except SlugUnavailable:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="slug unavailable",
            ) from None
        except IntegrityError:
            # Rare race: slug was free at pre-check, taken by a
            # concurrent signup before our INSERT landed.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="slug unavailable",
            ) from None

        session_row, refresh_plain = await sessions_svc.issue(
            db, user_id=user.id, user_agent=user_agent, ip_address=ip
        )

        await audit.record(
            db,
            action="user.signup",
            actor_kind=ActorKind.user,
            org_id=org.id,
            actor_user_id=user.id,
            target_type="user",
            target_id=str(user.id),
            ip_address=ip,
            user_agent=user_agent,
        )

        access, access_ttl = tokens.issue_access_token(
            user_id=user.id, session_id=session_row.id
        )

        return SignupResponse(
            access_token=access,
            refresh_token=refresh_plain,
            access_expires_in=access_ttl,
            user=UserOut.model_validate(user),
            org=OrgOut.model_validate(org),
        )


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request) -> LoginResponse:
    user_agent, ip = _client_info(request)
    async with admin_session() as db:
        try:
            user = await users_svc.authenticate(
                db, email=body.email, password=body.password
            )
        except InvalidCredentials:
            await audit.record(
                db,
                action="user.login.failure",
                actor_kind=ActorKind.system,
                metadata={"email": body.email},
                ip_address=ip,
                user_agent=user_agent,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid credentials",
            ) from None

        session_row, refresh_plain = await sessions_svc.issue(
            db, user_id=user.id, user_agent=user_agent, ip_address=ip
        )

        await audit.record(
            db,
            action="user.login.success",
            actor_kind=ActorKind.user,
            actor_user_id=user.id,
            target_type="session",
            target_id=str(session_row.id),
            ip_address=ip,
            user_agent=user_agent,
        )

        access, access_ttl = tokens.issue_access_token(
            user_id=user.id, session_id=session_row.id
        )
        return LoginResponse(
            access_token=access,
            refresh_token=refresh_plain,
            access_expires_in=access_ttl,
            user=UserOut.model_validate(user),
        )


@router.post("/refresh", response_model=TokenBundle)
async def refresh(body: RefreshRequest, request: Request) -> TokenBundle:
    user_agent, ip = _client_info(request)
    async with admin_session() as db:
        try:
            new_session, refresh_plain = await sessions_svc.rotate(
                db,
                refresh_token=body.refresh_token,
                user_agent=user_agent,
                ip_address=ip,
            )
        except SessionReuseDetected as exc:
            # A revoked refresh token was presented. Assume compromise
            # and revoke every session for the user.
            await sessions_svc.revoke_all_for_user(db, exc.user_id)
            await audit.record(
                db,
                action="session.reuse_detected",
                actor_kind=ActorKind.system,
                actor_user_id=exc.user_id,
                ip_address=ip,
                user_agent=user_agent,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="session revoked",
            ) from None
        except SessionNotFound:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid refresh token",
            ) from None

        access, access_ttl = tokens.issue_access_token(
            user_id=new_session.user_id, session_id=new_session.id
        )
        return TokenBundle(
            access_token=access,
            refresh_token=refresh_plain,
            access_expires_in=access_ttl,
        )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def logout(current: CurrentUser = Depends(get_current_user)) -> Response:
    async with admin_session() as db:
        await sessions_svc.revoke_by_id(db, current.claims.session_id)
        await audit.record(
            db,
            action="user.logout",
            actor_kind=ActorKind.user,
            actor_user_id=current.id,
            target_type="session",
            target_id=str(current.claims.session_id),
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
