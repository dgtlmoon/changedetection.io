"""WatchTag request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{3,8}$")
    settings: dict[str, Any] = Field(default_factory=dict)


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    name: str
    color: str | None
    settings: dict[str, Any]
    created_at: datetime


class TagListOut(BaseModel):
    tags: list[TagOut]


class TagAssignRequest(BaseModel):
    tag_ids: list[UUID] = Field(default_factory=list)


class TagAssignResponse(BaseModel):
    tags: list[TagOut]
