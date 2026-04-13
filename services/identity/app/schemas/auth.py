"""Pydantic schemas for the Phase-2a auth endpoints."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---------- Requests ---------------------------------------------------------


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    org_name: str = Field(min_length=1, max_length=100)
    # Optional; if absent we derive from org_name.
    org_slug: str | None = Field(default=None, min_length=3, max_length=40)
    display_name: str | None = Field(default=None, max_length=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=16, max_length=256)


# ---------- Responses --------------------------------------------------------


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    display_name: str | None = None
    locale: str
    timezone: str


class OrgOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str


class MembershipOut(BaseModel):
    role: str
    org: OrgOut


class TokenBundle(BaseModel):
    """Response body from signup / login / refresh."""

    access_token: str
    refresh_token: str
    access_expires_in: int = Field(description="Access-token lifetime in seconds.")


class SignupResponse(TokenBundle):
    user: UserOut
    org: OrgOut
    role: str = "owner"


class LoginResponse(TokenBundle):
    user: UserOut


class MeResponse(BaseModel):
    user: UserOut
    memberships: list[MembershipOut]


class LogoutResponse(BaseModel):
    """Present for OpenAPI completeness; the route returns 204 No Content."""
