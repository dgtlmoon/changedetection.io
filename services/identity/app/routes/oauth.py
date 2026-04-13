"""GET /v1/auth/oauth/{provider}/{start,callback}."""

from __future__ import annotations

from fastapi import APIRouter, Cookie, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from ..config import get_settings
from ..db import admin_session
from ..models.audit_log import ActorKind
from ..oauth import (
    STATE_COOKIE_NAME,
    STATE_TTL_SECONDS,
    decode_state,
    encode_state,
    get_registry,
)
from ..oauth.state import InvalidStateError, states_match
from ..schemas.auth import UserOut
from ..security import tokens
from ..services import audit, oauth as oauth_svc, sessions as sessions_svc
from ..services.oauth import UnverifiedEmailCollision

router = APIRouter(prefix="/v1/auth/oauth", tags=["auth"])


class OAuthCompleteResponse(BaseModel):
    access_token: str
    refresh_token: str
    access_expires_in: int
    user: UserOut
    is_new_user: bool


def _redirect_uri_for(provider_name: str) -> str:
    base = get_settings().oauth_redirect_base_url.rstrip("/")
    return f"{base}/v1/auth/oauth/{provider_name}/callback"


def _cookie_kwargs() -> dict:
    settings = get_settings()
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": settings.environment == "production",
        "max_age": STATE_TTL_SECONDS,
        "path": "/v1/auth/oauth",
    }


@router.get("/{provider}/start")
async def start(
    provider: str,
    redirect_to: str | None = Query(default=None, max_length=512),
) -> Response:
    providers = get_registry()
    if provider not in providers:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    state = encode_state(redirect_to=redirect_to)
    url = providers[provider].authorize_url(
        state=state, redirect_uri=_redirect_uri_for(provider)
    )

    resp = RedirectResponse(url=url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    resp.set_cookie(STATE_COOKIE_NAME, state, **_cookie_kwargs())
    return resp


@router.get("/{provider}/callback", response_model=OAuthCompleteResponse)
async def callback(
    provider: str,
    request: Request,
    code: str = Query(..., min_length=1, max_length=1024),
    state: str = Query(..., min_length=1, max_length=1024),
    cookie_state: str | None = Cookie(default=None, alias=STATE_COOKIE_NAME),
) -> JSONResponse:
    providers = get_registry()
    if provider not in providers:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    # State validation.
    if not cookie_state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing state cookie")
    if not states_match(cookie_state, state):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="state mismatch")
    try:
        decode_state(state)
    except InvalidStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from None

    # Exchange + profile fetch (provider implementation may hit HTTP).
    try:
        profile = await providers[provider].exchange_code(
            code=code, redirect_uri=_redirect_uri_for(provider)
        )
    except Exception:  # noqa: BLE001 — provider errors are all callable 400s
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="provider exchange failed",
        ) from None

    ua = request.headers.get("user-agent")
    ip = request.client.host if request.client else None

    async with admin_session() as db:
        try:
            user, is_new = await oauth_svc.sign_in_or_register(
                db, profile=profile
            )
        except UnverifiedEmailCollision:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "an account already exists for this email; please log "
                    "in with your password and link your provider from "
                    "account settings"
                ),
            ) from None

        session_row, refresh_plain = await sessions_svc.issue(
            db, user_id=user.id, user_agent=ua, ip_address=ip
        )

        await audit.record(
            db,
            action=("user.signup.oauth" if is_new else "user.login.oauth"),
            actor_kind=ActorKind.user,
            actor_user_id=user.id,
            target_type="user",
            target_id=str(user.id),
            metadata={"provider": provider},
            ip_address=ip,
            user_agent=ua,
        )

        access_token, access_ttl = tokens.issue_access_token(
            user_id=user.id, session_id=session_row.id
        )
        body = OAuthCompleteResponse(
            access_token=access_token,
            refresh_token=refresh_plain,
            access_expires_in=access_ttl,
            user=UserOut.model_validate(user),
            is_new_user=is_new,
        )

    # Return JSON + clear the state cookie.
    resp = JSONResponse(body.model_dump(mode="json"))
    resp.delete_cookie(STATE_COOKIE_NAME, path="/v1/auth/oauth")
    return resp
