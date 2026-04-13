"""
URL normalization for the site_inventory_diff processor.

The goal: reduce noise-driven false positives so the diff only fires when a
*real* page is added or removed, not when the site gains a new UTM parameter or
swaps a trailing slash.

Every URL stored in the snapshot passes through canonical_url(). The rules are
deliberately boring — if a rule here is wrong, the whole system flaps. Changes
to this file should come with a test in tests/site_inventory/test_normalize.py.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional
from urllib.parse import urlsplit, urlunsplit, urljoin, quote, unquote


# --- Defaults --------------------------------------------------------------

# Query parameters that are essentially identity noise. Dropped even when
# the user opts to keep query strings, because they never change the page.
_TRACKING_PARAM_RE = re.compile(
    r"^(utm_[a-z_]+|"
    r"gclid|fbclid|dclid|msclkid|mc_[a-z_]+|"
    r"_hs[a-z]*|hsCtaTracking|"
    r"ref|ref_src|ref_url|source|campaign|"
    r"yclid|igshid|mkt_tok|vero_id|trk|"
    r"_ga|_gl)$",
    re.IGNORECASE,
)

# Schemes we don't want to treat as "pages".
_NON_PAGE_SCHEMES = frozenset(
    {"mailto", "tel", "javascript", "data", "ftp", "ws", "wss", "blob", "about"}
)


def _split_querystring(qs: str) -> list[tuple[str, str]]:
    """Parse a raw query string into (key, value) pairs without URL-decoding
    values (so we can round-trip them). Empty pairs are dropped.
    """
    out: list[tuple[str, str]] = []
    if not qs:
        return out
    for pair in qs.split("&"):
        if not pair:
            continue
        if "=" in pair:
            k, v = pair.split("=", 1)
        else:
            k, v = pair, ""
        out.append((k, v))
    return out


def _join_querystring(pairs: Iterable[tuple[str, str]]) -> str:
    return "&".join(f"{k}={v}" if v != "" else k for k, v in pairs)


def canonical_url(
    url: str,
    base_url: Optional[str] = None,
    *,
    strip_query: bool = True,
    strip_tracking_params_always: bool = True,
    keep_trailing_slash_on_root: bool = True,
) -> Optional[str]:
    """Return a canonical form of ``url`` suitable for diffing.

    Returns ``None`` if the URL should be skipped entirely (unsupported
    scheme, invalid host, etc).

    Rules applied (in order):

    1. Resolve relative URLs against ``base_url``.
    2. Drop fragments (``#foo``). A fragment never denotes a new page.
    3. Lowercase scheme and host.
    4. Strip default port for the scheme.
    5. Remove the query string when ``strip_query`` is true, else remove only
       tracking params when ``strip_tracking_params_always`` is true.
    6. Normalize trailing slash: single path segments keep their slash, all
       other paths have their trailing slash stripped.
    7. Re-encode the path (idempotent).
    """

    if not url:
        return None

    url = url.strip()
    if not url:
        return None

    if base_url:
        try:
            url = urljoin(base_url, url)
        except ValueError:
            return None

    try:
        parts = urlsplit(url)
    except ValueError:
        return None

    scheme = (parts.scheme or "").lower()
    if scheme in _NON_PAGE_SCHEMES:
        return None
    if scheme not in ("http", "https"):
        # Only treat http(s) as pages; everything else is either a non-page
        # or too weird to normalize safely.
        return None

    host = (parts.hostname or "").lower()
    if not host:
        return None

    # Strip default ports
    port = parts.port
    netloc = host
    if port and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        netloc = f"{host}:{port}"

    # Userinfo is extremely unusual on public pages; preserve only if present.
    if parts.username:
        userinfo = parts.username
        if parts.password:
            userinfo += f":{parts.password}"
        netloc = f"{userinfo}@{netloc}"

    # Query handling
    query = ""
    if parts.query:
        if strip_query:
            query = ""
        else:
            pairs = _split_querystring(parts.query)
            if strip_tracking_params_always:
                pairs = [
                    (k, v) for (k, v) in pairs if not _TRACKING_PARAM_RE.match(k)
                ]
            # Sort so ordering differences never cause flapping.
            pairs.sort(key=lambda kv: kv[0])
            query = _join_querystring(pairs)

    # Path normalization
    path = parts.path or "/"
    # Re-encode safely: decode then quote with standard safe set.
    try:
        path_dec = unquote(path)
        path = quote(path_dec, safe="/-._~!$&'()*+,;=:@%")
    except (UnicodeDecodeError, ValueError):
        # Keep original if we somehow can't re-encode (garbage in — leave it).
        pass

    # Collapse accidental double slashes (but not the empty path).
    while "//" in path:
        path = path.replace("//", "/")

    # Trailing slash rule
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/") or "/"
    elif path == "" and keep_trailing_slash_on_root:
        path = "/"

    return urlunsplit((scheme, netloc, path, query, ""))


# --- Host comparison ------------------------------------------------------

def _registrable_host(host: str) -> str:
    """Rough 'same-site' comparison key.

    Strips a leading ``www.`` so ``example.com`` and ``www.example.com`` compare
    equal. We deliberately do NOT attempt full public-suffix matching; it's
    overkill for a change-detection tool and would add a dependency (tldextract)
    we don't need.
    """
    if not host:
        return ""
    host = host.lower().strip()
    return host[4:] if host.startswith("www.") else host


def same_origin(url_a: str, url_b: str) -> bool:
    """Return True if ``url_a`` and ``url_b`` share a 'site' for inventory
    purposes (scheme is ignored; ``www.`` prefix is ignored).
    """
    try:
        a = urlsplit(url_a)
        b = urlsplit(url_b)
    except ValueError:
        return False
    return _registrable_host(a.hostname or "") == _registrable_host(b.hostname or "")


# --- Dedupe + sort --------------------------------------------------------

def dedupe_and_sort(urls: Iterable[str]) -> list[str]:
    """Remove duplicates (preserving canonical form already applied) and
    return a stable, sorted list.
    """
    return sorted({u for u in urls if u})
