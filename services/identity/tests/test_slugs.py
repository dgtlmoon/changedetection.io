"""Unit tests for slug validation + derivation."""

from __future__ import annotations

import pytest

from app.services import slugs


@pytest.mark.parametrize(
    "slug,expected",
    [
        ("acme", True),
        ("beta-co", True),
        ("a-b-c", True),
        ("abc123", True),
        # Too short
        ("ab", False),
        # Leading / trailing hyphen
        ("-bad", False),
        ("bad-", False),
        # Non-alnum
        ("has space", False),
        ("HAS_UPPER", False),
        ("has.dot", False),
        # Reserved
        ("api", False),
        ("www", False),
        ("admin", False),
    ],
)
def test_is_valid(slug: str, expected: bool) -> None:
    assert slugs.is_valid(slug) is expected


@pytest.mark.parametrize(
    "name,expected_prefix",
    [
        ("Acme Corp", "acme-corp"),
        ("Acme   Corp!!", "acme-corp"),
        ("acme-corp", "acme-corp"),
        ("Acme & Co", "acme-co"),
    ],
)
def test_derive_produces_clean_slug(name: str, expected_prefix: str) -> None:
    s = slugs.derive_from_name(name)
    assert slugs.SLUG_RE.match(s), f"derived slug {s!r} failed regex"
    assert s.startswith(expected_prefix)


def test_derive_from_junk_returns_random_slug() -> None:
    s = slugs.derive_from_name("!!")
    assert slugs.SLUG_RE.match(s)
    assert s.startswith("org-")


def test_with_random_suffix_stays_within_40_chars() -> None:
    base = "x" * 40
    out = slugs.with_random_suffix(base)
    assert len(out) <= 40
    assert slugs.SLUG_RE.match(out)


def test_with_random_suffix_adds_entropy() -> None:
    a = slugs.with_random_suffix("acme")
    b = slugs.with_random_suffix("acme")
    assert a != b
    assert a.startswith("acme-")
