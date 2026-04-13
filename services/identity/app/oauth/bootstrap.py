"""Register OAuth providers from environment configuration.

Called once at app startup. A provider is registered only when both
``client_id`` and ``client_secret`` are set — missing config silently
disables that provider, so ``/v1/auth/oauth/{missing}/start`` returns
404 rather than crashing on startup.
"""

from __future__ import annotations

import structlog

from ..config import get_settings
from .github import GitHubProvider
from .google import GoogleProvider
from .provider import register

_log = structlog.get_logger()


def register_from_settings() -> list[str]:
    """Register all configured providers. Returns list of provider names."""
    settings = get_settings()
    names: list[str] = []

    if settings.oauth_google_client_id and settings.oauth_google_client_secret:
        register(
            GoogleProvider(
                client_id=settings.oauth_google_client_id,
                client_secret=settings.oauth_google_client_secret,
            )
        )
        names.append("google")

    if settings.oauth_github_client_id and settings.oauth_github_client_secret:
        register(
            GitHubProvider(
                client_id=settings.oauth_github_client_id,
                client_secret=settings.oauth_github_client_secret,
            )
        )
        names.append("github")

    _log.info("oauth.providers_registered", providers=names)
    return names
