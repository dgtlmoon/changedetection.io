"""Watch request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class WatchCreate(BaseModel):
    url: HttpUrl
    title: str | None = Field(default=None, max_length=200)
    processor: str = Field(default="text_json_diff", max_length=50)
    fetch_backend: str = Field(default="system", max_length=50)
    time_between_check_seconds: int | None = Field(default=None, ge=0)
    settings: dict[str, Any] = Field(default_factory=dict)


class WatchPatchIn(BaseModel):
    """PATCH body — all fields optional."""

    model_config = ConfigDict(extra="forbid")

    url: HttpUrl | None = None
    title: str | None = None
    processor: str | None = None
    fetch_backend: str | None = None
    paused: bool | None = None
    notification_muted: bool | None = None
    time_between_check_seconds: int | None = None
    settings: dict[str, Any] | None = None


class WatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    url: str
    title: str | None
    processor: str
    fetch_backend: str
    paused: bool
    notification_muted: bool
    time_between_check_seconds: int | None
    last_checked: datetime | None
    last_changed: datetime | None
    last_error: str | None
    check_count: int
    previous_md5: str | None
    settings: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class WatchListOut(BaseModel):
    watches: list[WatchOut]
    limit: int
    offset: int
