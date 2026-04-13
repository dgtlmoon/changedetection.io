"""Org-slug derivation + reserved-word policy."""

from __future__ import annotations

import re
import secrets

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")

# Reserved slugs that cannot be assigned to an org. Either they collide
# with an existing or planned subdomain, or they are confusable /
# phishing-friendly. Keep sorted for grep-ability.
RESERVED_SLUGS: frozenset[str] = frozenset(
    {
        "about",
        "admin",
        "api",
        "app",
        "auth",
        "billing",
        "blog",
        "careers",
        "cdn",
        "dashboard",
        "docs",
        "download",
        "email",
        "ftp",
        "help",
        "imap",
        "invoices",
        "jobs",
        "login",
        "mail",
        "oauth",
        "pop",
        "pricing",
        "privacy",
        "security",
        "signup",
        "smtp",
        "static",
        "status",
        "support",
        "terms",
        "webhooks",
        "www",
    }
)


def is_valid(slug: str) -> bool:
    """True if the slug is syntactically acceptable and not reserved."""
    return bool(SLUG_RE.match(slug)) and slug not in RESERVED_SLUGS


_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_RUNS = re.compile(r"-+")


def derive_from_name(name: str) -> str:
    """Best-effort slug derived from an org name. Not guaranteed unique.

    Always returns a syntactically valid slug (3-40 chars, no leading /
    trailing hyphen) — falls back to a random string if the input is
    too stripped to be useful.
    """
    s = _NON_ALNUM.sub("-", name.lower())
    s = _RUNS.sub("-", s).strip("-")
    if len(s) < 3:
        # e.g. name was "!!" or empty — emit a random slug.
        return "org-" + secrets.token_hex(4)
    return s[:40].rstrip("-")


def with_random_suffix(base: str) -> str:
    """Append a 6-hex-digit suffix, trimming ``base`` if needed so the
    result stays within the 40-char limit.
    """
    suffix = "-" + secrets.token_hex(3)
    max_base = 40 - len(suffix)
    return (base[:max_base].rstrip("-")) + suffix
