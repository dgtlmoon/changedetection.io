"""Argon2id password hashing.

Picked parameters follow OWASP 2024 guidance:
  - time_cost=3, memory_cost=64 MiB, parallelism=4
  - hashed strings are self-describing, so migrating parameters later
    is a rehash-on-next-verify strategy.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerifyMismatchError

_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,  # 64 MiB
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


def hash_password(plaintext: str) -> str:
    """Return a self-describing Argon2id hash string."""
    if not plaintext:
        raise ValueError("password cannot be empty")
    return _hasher.hash(plaintext)


def verify_password(plaintext: str, hashed: str) -> bool:
    """Verify a plaintext password against a stored hash.

    Returns True on match, False on mismatch *or* invalid hash (we never
    leak the difference to the caller — both are auth failures).
    """
    try:
        return _hasher.verify(hashed, plaintext)
    except (VerifyMismatchError, InvalidHash):
        return False


def needs_rehash(hashed: str) -> bool:
    """True if the stored hash uses parameters below the current policy."""
    return _hasher.check_needs_rehash(hashed)
