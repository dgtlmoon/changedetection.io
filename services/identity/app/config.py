"""Runtime configuration loaded from the environment via pydantic-settings."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration. Environment variables are prefixed ``IDENTITY_``."""

    model_config = SettingsConfigDict(
        env_prefix="IDENTITY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Database ------------------------------------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://app_runtime:app_runtime_dev_password"
        "@localhost:5432/onchange",
        description=(
            "Async Postgres URL for the app_runtime role. This role respects "
            "row-level-security policies. Used on the request hot path."
        ),
    )
    database_admin_url: str = Field(
        default="postgresql+asyncpg://identity_admin:identity_admin_dev_password"
        "@localhost:5432/onchange",
        description=(
            "Async Postgres URL for the identity_admin role (BYPASSRLS). "
            "Used only for cross-org lookups in auth code paths."
        ),
    )

    # --- Redis ---------------------------------------------------------------
    redis_url: str = Field(default="redis://localhost:6379/0")

    # --- Tenancy -------------------------------------------------------------
    root_domain: str = Field(
        default="change.sairo.app",
        description=(
            "Bare-domain suffix used by the tenant resolver. A request Host of "
            "``acme.change.sairo.app`` resolves to org slug ``acme``."
        ),
    )

    # --- Secrets -------------------------------------------------------------
    secret_key: str = Field(
        default="dev-only-do-not-use-in-production",
        description="Used to sign access JWTs from Phase 2 onwards.",
    )

    # --- Runtime -------------------------------------------------------------
    environment: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance.

    Using ``lru_cache`` so tests can monkeypatch env vars and then call
    ``get_settings.cache_clear()`` to pick up changes.
    """
    return Settings()
