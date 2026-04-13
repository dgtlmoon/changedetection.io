"""Pydantic schemas for the Phase-2d API-key endpoints."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyScope(str, Enum):
    watches_read = "watches:read"
    watches_write = "watches:write"
    admin = "admin"


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[ApiKeyScope] = Field(min_length=1)
    expires_at: datetime | None = None


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    key_prefix: str
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None


class ApiKeyCreateResponse(ApiKeyOut):
    """Returned once, on create. ``plaintext_key`` never appears again."""

    plaintext_key: str


class ApiKeyListOut(BaseModel):
    api_keys: list[ApiKeyOut]
