"""ObjectStore protocol + shared exceptions + key validation."""

from __future__ import annotations

import re
from typing import Protocol


class ObjectNotFound(Exception):
    """Raised by ``get`` / ``delete`` when the key doesn't exist."""


class InvalidObjectKey(Exception):
    """Raised when a caller hands us a key that fails validation.

    Validation is strict because we want to fail fast on caller bugs
    and defend against traversal / null-injection attacks reaching the
    backend.
    """


# Keys look like ``{org_id}/watches/{watch_id}/snapshots/2026-04-13T…``.
# No leading slash. No ``..`` segments. No backslashes. Printable ASCII
# only. Length cap defends against S3's 1024-byte key limit.
_KEY_RE = re.compile(r"^(?!/)(?!.*\.\.)(?!.*\\)[\x21-\x7e/]{1,1000}$")


def validate_key(key: str) -> None:
    """Raise :class:`InvalidObjectKey` if ``key`` is unsafe."""
    if not _KEY_RE.match(key):
        raise InvalidObjectKey(key)


class ObjectStore(Protocol):
    """Backend for snapshot bodies, screenshots, PDFs, favicons.

    Implementations are expected to be idempotent on ``put`` (overwrite
    is fine) and to raise :class:`ObjectNotFound` on ``get``/``delete``
    of a missing key.
    """

    async def put(self, key: str, body: bytes, *, content_type: str) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...

    async def presigned_url(self, key: str, *, expires_in: int = 3600) -> str: ...
