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

    # --- Tenancy + auth ------------------------------------------------------
    # Must match the identity service's IDENTITY_ROOT_DOMAIN. The
    # tenant resolver peels the first subdomain label off this.
    root_domain: str = "change.sairo.app"
    # Must match IDENTITY_SECRET_KEY. We verify JWTs with the same
    # HS256 key so the two services don't need to talk over HTTP on
    # the auth hot path.
    secret_key: str = "dev-only-do-not-use-in-production"

    # --- Object storage ------------------------------------------------------
    object_store_backend: Literal["local", "s3"] = "local"
    # LocalObjectStore root. Ignored unless backend=local.
    object_store_local_root: str = "./var/object-store"
    # S3 (or compatible: R2, MinIO). Ignored unless backend=s3.
    object_store_s3_bucket: str | None = None
    object_store_s3_region: str | None = None
    object_store_s3_endpoint_url: str | None = None
    object_store_s3_access_key_id: str | None = None
    object_store_s3_secret_access_key: str | None = None

    environment: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
