"""Pydantic schemas for the Phase-2c invite endpoints."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from ..models.membership import MembershipRole
from .auth import OrgOut, TokenBundle, UserOut

# Invites cannot assign the ``owner`` role — org creation is the only
# path to owner. Enforced at the pydantic layer.
InviteRole = MembershipRole


class InviteCreate(BaseModel):
    email: EmailStr
    role: InviteRole = Field(
        default=MembershipRole.member,
        description="One of admin/member/viewer. ``owner`` is rejected.",
    )


class InviteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    role: str
    expires_at: datetime
    created_at: datetime
    accepted_at: datetime | None = None


class InviteListOut(BaseModel):
    invites: list[InviteOut]


class InviteAcceptRequest(BaseModel):
    token: str = Field(min_length=16, max_length=256)
    # Required when the accepting email has no existing user, or when
    # the caller has no bearer token and the user isn't logged in.
    password: str | None = Field(default=None, min_length=12, max_length=256)
    display_name: str | None = Field(default=None, max_length=100)


class InviteAcceptResponse(TokenBundle):
    user: UserOut
    org: OrgOut
    role: str
