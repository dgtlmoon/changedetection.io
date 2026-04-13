"""Unit tests for the tokens module. No DB, no network."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.security import tokens


def test_access_token_roundtrip() -> None:
    user_id = uuid4()
    session_id = uuid4()

    token, expires_in = tokens.issue_access_token(
        user_id=user_id, session_id=session_id
    )
    assert isinstance(token, str) and token.count(".") == 2
    assert 0 < expires_in <= int(tokens.ACCESS_TOKEN_TTL.total_seconds())

    claims = tokens.decode_access_token(token)
    assert claims.user_id == user_id
    assert claims.session_id == session_id
    assert claims.expires_at > claims.issued_at


def test_access_token_rejects_tampering() -> None:
    token, _ = tokens.issue_access_token(user_id=uuid4(), session_id=uuid4())
    tampered = token[:-4] + ("AAAA" if token[-4:] != "AAAA" else "BBBB")
    with pytest.raises(tokens.TokenError):
        tokens.decode_access_token(tampered)


def test_access_token_rejects_wrong_type(monkeypatch) -> None:
    """A refresh-token-shaped JWT (or any non-``access`` type) must be rejected."""
    from jose import jwt as _jwt

    from app.config import get_settings

    settings = get_settings()
    now = datetime.now(timezone.utc)
    bad = _jwt.encode(
        {
            "sub": str(uuid4()),
            "sid": str(uuid4()),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "type": "refresh",  # wrong!
        },
        settings.secret_key,
        algorithm="HS256",
    )
    with pytest.raises(tokens.TokenError):
        tokens.decode_access_token(bad)


def test_access_token_rejects_expired() -> None:
    # Can't easily inject a negative TTL without monkey-patching;
    # verify by issuing a token with an expiry in the past.
    from jose import jwt as _jwt

    from app.config import get_settings

    settings = get_settings()
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    token = _jwt.encode(
        {
            "sub": str(uuid4()),
            "sid": str(uuid4()),
            "iat": int(past.timestamp()) - 60,
            "exp": int(past.timestamp()),
            "type": "access",
        },
        settings.secret_key,
        algorithm="HS256",
    )
    with pytest.raises(tokens.TokenError):
        tokens.decode_access_token(token)


def test_new_refresh_token_is_unique() -> None:
    a, ha = tokens.new_refresh_token()
    b, hb = tokens.new_refresh_token()
    assert a != b
    assert ha != hb
    # Hash should be deterministic.
    assert tokens.hash_refresh_token(a) == ha


def test_refresh_expiry_is_in_the_future() -> None:
    assert tokens.refresh_expiry() > datetime.now(timezone.utc)


def test_new_refresh_token_entropy() -> None:
    """Smoke-test: 1000 tokens, zero collisions."""
    seen = set()
    for _ in range(1000):
        plain, _ = tokens.new_refresh_token()
        assert plain not in seen
        seen.add(plain)
