"""Argon2id password hashing."""

from __future__ import annotations

import pytest

from app.security.passwords import hash_password, needs_rehash, verify_password


def test_hash_then_verify_roundtrip() -> None:
    h = hash_password("correct horse battery staple")
    assert h.startswith("$argon2id$")
    assert verify_password("correct horse battery staple", h) is True


def test_verify_rejects_wrong_password() -> None:
    h = hash_password("correct horse battery staple")
    assert verify_password("wrong password", h) is False


def test_verify_rejects_malformed_hash() -> None:
    # Invalid hash string must fail verification, NOT raise.
    assert verify_password("anything", "not-a-real-hash") is False


def test_hash_produces_different_outputs_each_call() -> None:
    """Salts must differ run-to-run (Argon2 handles this internally)."""
    a = hash_password("same-password")
    b = hash_password("same-password")
    assert a != b


def test_empty_password_is_rejected() -> None:
    with pytest.raises(ValueError):
        hash_password("")


def test_needs_rehash_is_false_for_current_params() -> None:
    h = hash_password("x")
    assert needs_rehash(h) is False
