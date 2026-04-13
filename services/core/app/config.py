"""Runtime configuration for the core service."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration. Env vars are prefixed ``CORE_``."""

    model_config = SettingsConfigDict(
        env_prefix="CORE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+asyncpg://app_runtime:app_runtime_dev_password"
        "@localhost:5432/onchange",
        description=(
            "Async Postgres URL for the app_runtime role. RLS-respecting."
        ),
    )
    database_admin_url: str = Field(
        default="postgresql+asyncpg://identity_admin:identity_admin_dev_password"
        "@localhost:5432/onchange",
        description=(
            "Async Postgres URL for the identity_admin role (BYPASSRLS). "
            "Used by Alembic; never by the request hot path."
        ),
    )

    environment: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
