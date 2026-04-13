"""Domain errors raised by the services layer.

Route handlers translate these to HTTP responses. The services layer
never raises ``HTTPException`` directly — keeps the modules testable
without FastAPI.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for domain-level errors."""


class EmailAlreadyRegistered(DomainError):
    """Signup tried to register an email that already exists."""


class SlugUnavailable(DomainError):
    """Requested org slug is reserved or already taken."""


class InvalidCredentials(DomainError):
    """Wrong email/password, or user does not exist.

    Route handlers MUST map this to a generic 401 — never reveal
    whether the email exists (user enumeration).
    """


class SessionNotFound(DomainError):
    """Refresh token does not match any non-revoked session."""


class SessionReuseDetected(DomainError):
    """A revoked refresh token was presented — credential-stuffing signal.

    Carries the ``user_id`` so the caller can trigger a revoke-all
    without a second DB lookup.
    """

    def __init__(self, user_id) -> None:  # type: ignore[no-untyped-def]
        super().__init__("session reuse detected")
        self.user_id = user_id
