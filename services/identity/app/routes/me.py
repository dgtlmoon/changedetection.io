"""GET /v1/me — current user + their memberships."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..db import admin_session
from ..schemas.auth import MembershipOut, MeResponse, OrgOut, UserOut
from ..security.deps import CurrentUser, get_current_user
from ..services import orgs as orgs_svc

router = APIRouter(prefix="/v1", tags=["me"])


@router.get("/me", response_model=MeResponse)
async def me(current: CurrentUser = Depends(get_current_user)) -> MeResponse:
    async with admin_session() as db:
        memberships = await orgs_svc.memberships_for_user(db, current.id)
    return MeResponse(
        user=UserOut.model_validate(current.user),
        memberships=[
            MembershipOut(role=m.role.value, org=OrgOut.model_validate(m.org))
            for m in memberships
        ],
    )
