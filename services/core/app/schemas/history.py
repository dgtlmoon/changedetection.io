"""WatchHistoryEntry response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class HistoryEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    watch_id: UUID
    taken_at: datetime
    kind: str
    content_type: str
    size_bytes: int
    hash_md5: str
    created_at: datetime


class HistoryListOut(BaseModel):
    entries: list[HistoryEntryOut]
    limit: int
    offset: int
