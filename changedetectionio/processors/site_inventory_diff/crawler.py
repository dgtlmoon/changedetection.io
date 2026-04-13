"""
Bounded same-origin crawler for the site_inventory_diff processor.

Design goals:

* Bounded in every dimension — max pages, max depth, overall budget in seconds.
* Well-behaved — obeys robots.txt (including the ``Crawl-delay`` directive) by
  default, spaces requests by a user-set delay, sends a clear User-Agent
  (``onChange-Inventory/<version>`` unless the watch overrides it).
* Same-origin only — follows links that share a registrable host with the seed.
* Deterministic — BFS with sorted frontier, so snapshot ordering is stable.
* SSRF-safe — every outbound URL (seed, redirects, follow-up links, and the
  robots.txt fetch itself) is screened against IANA private/reserved ranges
  unless the operator has explicitly opted in via ``ALLOW_IANA_RESTRICTED_ADDRESSES``.
* Integration-aware — accepts the watch's configured proxy, request headers,
  and a pre-fetched seed body so we don't re-issue the seed HTTP call the
  worker already made.

The crawler is intentionally self-contained (``requests``-only, no Playwright).
For most URL-inventory use cases a full browser is overkill; users who need JS
rendering can still use the sitemap or listing-page modes with any fetcher.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Iterable, Mapping, Optional
from urllib import robotparser
from urllib.parse import urlsplit

import requests
from loguru import logger

from changedetectionio.strtobool import strtobool
from changedetectionio.validate_url import is_private_hostname

from . import extractors
from . import normalize


# Conservative default — every request carries an identifying UA so site
# operators can contact us / rate-limit us gracefully.
DEFAULT_USER_AGENT = "onChange-Inventory-Crawler/1.0 (+https://change.sairo.app)"

# robots.txt cache TTL. A watch that runs hourly shouldn't fetch robots.txt
# hourly; an hour of caching is plenty and errs on the side of freshness.
_ROBOTS_CACHE_TTL_SECONDS = 3600

# Module-level robots cache keyed on (scheme, netloc, user_agent). Thread-safe
# with a coarse lock — lookups are infrequent relative to crawl request rate.
_robots_cache: dict[tuple[str, str, str], tuple[Optional[robotparser.RobotFileParser], float]] = {}
_robots_cache_lock = threading.Lock()


# Fraction of child fetches that must fail before we surface a warning and
# (optionally) set a watch-level error. Chosen so small flakes don't spam the
# UI, but a Cloudflare challenge wall or broken DNS does.
FETCH_FAILURE_WARNING_THRESHOLD = 0.5


class CrawlResult:
    """Accumulated crawler output.

    Attributes:
        urls: Canonicalized URLs discovered.
        pages_fetched: Number of pages actually fetched (2xx).
        pages_failed: Number of pages whose HTTP call failed (network error or
            non-2xx). Used by the processor to surface warnings when the
            failure rate is high.
        pages_skipped_robots: Pages skipped because robots.txt disallowed.
        pages_skipped_ssrf: Pages skipped because they resolved to a
            private/reserved IP range (SSRF guard).
        hit_max_pages: True if the ``max_pages`` cap was reached.
        hit_max_depth: True if any link was skipped due to ``max_depth``.
        hit_time_budget: True if ``time_budget_seconds`` was exhausted.
        warnings: Human-readable warnings to surface in the snapshot header.
    """

    __slots__ = (
        "urls",
        "pages_fetched",
        "pages_failed",
        "pages_skipped_robots",
        "pages_skipped_ssrf",
        "hit_max_pages",
        "hit_max_depth",
        "hit_time_budget",
        "warnings",
    )

    def __init__(self) -> None:
        self.urls: set[str] = set()
        self.pages_fetched = 0
        self.pages_failed = 0
        self.pages_skipped_robots = 0
        self.pages_skipped_ssrf = 0
        self.hit_max_pages = False
        self.hit_max_depth = False
        self.hit_time_budget = False
        self.warnings: list[str] = []

    @property
    def failure_rate(self) -> float:
        """Fraction of attempted fetches that failed. Zero if none were attempted."""
        attempts = self.pages_fetched + self.pages_failed
        return (self.pages_failed / attempts) if attempts else 0.0


# ---------------------------------------------------------------------------
# SSRF guard
# ---------------------------------------------------------------------------

def _ssrf_allowed(url: str) -> bool:
    """Return True if the URL is safe to fetch according to IANA rules.

    Honors the ``ALLOW_IANA_RESTRICTED_ADDRESSES`` env var for parity with
    ``processors/base.py::validate_iana_url``. Never raises — on any error we
    err on the side of *disallowing* the URL, which is the safe default.
    """
    if strtobool(os.getenv("ALLOW_IANA_RESTRICTED_ADDRESSES", "false")):
        return True
    try:
        host = urlsplit(url).hostname
    except (ValueError, AttributeError):
        return False
    if not host:
        return False
    try:
        return not is_private_hostname(host)
    except Exception as exc:
        logger.debug(f"SSRF check failed for {host!r}: {exc!r} — disallowing")
        return False


# ---------------------------------------------------------------------------
# robots.txt: cached, TTL-aware, SSRF-guarded
# ---------------------------------------------------------------------------

def _build_robots(
    seed_url: str,
    *,
    user_agent: str,
    timeout: float,
    session: requests.Session,
) -> Optional[robotparser.RobotFileParser]:
    """Load (or reuse) a parsed robots.txt for the seed's host.

    Results are cached for ``_ROBOTS_CACHE_TTL_SECONDS`` so a watch that runs
    hourly doesn't refetch robots.txt hourly.
    """
    parts = urlsplit(seed_url)
    if not parts.scheme or not parts.hostname:
        return None

    cache_key = (parts.scheme, parts.netloc, user_agent)
    now = time.monotonic()

    with _robots_cache_lock:
        cached = _robots_cache.get(cache_key)
        if cached is not None:
            parser, fetched_at = cached
            if now - fetched_at < _ROBOTS_CACHE_TTL_SECONDS:
                return parser

    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"

    rp = robotparser.RobotFileParser()
    # Missing / unfetchable robots.txt means "allow all". Pre-seed with empty
    # rules so can_fetch() returns True; we may overwrite below.
    rp.parse([])

    # SSRF guard on robots.txt itself — important, since a seed URL's host may
    # be fine to resolve but robots.txt could be redirected somewhere nasty.
    if _ssrf_allowed(robots_url):
        try:
            resp = session.get(
                robots_url,
                headers={"User-Agent": user_agent},
                timeout=timeout,
                allow_redirects=True,
            )
            if 200 <= resp.status_code < 300 and resp.text:
                rp.parse(resp.text.splitlines())
        except requests.RequestException as exc:
            logger.debug(f"robots.txt fetch failed for {robots_url}: {exc!r}")
    else:
        logger.debug(f"robots.txt URL {robots_url} blocked by SSRF guard")

    with _robots_cache_lock:
        _robots_cache[cache_key] = (rp, now)

    return rp


# ---------------------------------------------------------------------------
# HTTP — default client, used when the processor doesn't inject one
# ---------------------------------------------------------------------------

def _make_session(
    *,
    proxy_url: Optional[str] = None,
    extra_headers: Optional[Mapping[str, str]] = None,
) -> requests.Session:
    """Build a ``requests.Session`` with the watch's proxy + headers applied."""
    session = requests.Session()
    if proxy_url:
        session.proxies.update({"http": proxy_url, "https": proxy_url})
    if extra_headers:
        # User-Agent intentionally NOT set here; callers pass UA explicitly so
        # robots.txt matching and per-request overrides stay in sync.
        session.headers.update(
            {k: v for k, v in extra_headers.items() if k.lower() != "user-agent"}
        )
    return session


def _default_get_factory(session: requests.Session):
    """Return a ``http_get(url, user_agent, timeout)`` closure bound to ``session``."""

    def _get(url: str, *, user_agent: str, timeout: float) -> tuple[Optional[str], str, Optional[int]]:
        resp = session.get(
            url,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml",
            },
            timeout=timeout,
            allow_redirects=True,
        )
        status = resp.status_code
        ctype = resp.headers.get("Content-Type", "")
        if not (200 <= status < 300):
            return None, ctype, status
        return resp.text, ctype, status

    return _get


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------

def crawl(
    seed_url: str,
    *,
    max_pages: int = 100,
    max_depth: int = 2,
    crawl_delay_seconds: float = 1.0,
    time_budget_seconds: float = 60.0,
    respect_robots_txt: bool = True,
    user_agent: str = DEFAULT_USER_AGENT,
    request_timeout: float = 10.0,
    include_regex: Optional[str] = None,
    exclude_regex: Optional[str] = None,
    normalize_opts: Optional[dict] = None,
    # Integration knobs (populated by the processor from watch config):
    proxy_url: Optional[str] = None,
    extra_headers: Optional[Mapping[str, str]] = None,
    seed_body: Optional[str] = None,
    seed_content_type: str = "text/html",
    # Test hooks:
    _now: Optional[callable] = None,
    _sleep: Optional[callable] = None,
    _get: Optional[callable] = None,
    _session: Optional[requests.Session] = None,
) -> CrawlResult:
    """Run a bounded same-origin crawl starting from ``seed_url``.

    Args:
        proxy_url: HTTP/SOCKS proxy URL to use for every outbound request,
            including robots.txt. Typically the URL from the watch's proxy
            setting.
        extra_headers: Additional request headers applied to every fetch
            (robots.txt and content). Intended for cookies / auth headers
            configured on the watch. ``User-Agent`` is filtered out and must
            be passed via ``user_agent`` so it stays consistent with
            robots.txt matching.
        seed_body: If set, the crawler will treat this string as the body of
            the seed URL and skip the first HTTP call. The worker has already
            fetched the seed via the main fetcher stack, so this avoids a
            wasted double-fetch when source_type="crawl".
        seed_content_type: The content-type string associated with
            ``seed_body``. Used to decide whether to parse it as HTML.

    The last four underscore-prefixed args are test hooks — ``_now`` and
    ``_sleep`` let tests inject a fake clock, ``_get`` swaps the HTTP call,
    and ``_session`` lets tests supply a stub session when the closure path
    is exercised.
    """
    import re

    now = _now or time.monotonic
    sleep = _sleep or time.sleep

    # Build the session (or accept a test-supplied one).
    if _get is None:
        session = _session if _session is not None else _make_session(
            proxy_url=proxy_url, extra_headers=extra_headers
        )
        http_get = _default_get_factory(session)
    else:
        http_get = _get  # tests supply their own (url, user_agent, timeout) → tuple
        session = _session  # may be None; only used for robots.txt, gated below

    result = CrawlResult()

    seed = normalize.canonical_url(seed_url, **(normalize_opts or {}))
    if not seed:
        result.warnings.append(f"Invalid seed URL: {seed_url!r}")
        return result

    if not _ssrf_allowed(seed):
        result.warnings.append(
            "Seed URL resolves to a private/reserved IP range; crawl aborted."
        )
        result.pages_skipped_ssrf += 1
        return result

    robots: Optional[robotparser.RobotFileParser] = None
    effective_delay = float(crawl_delay_seconds or 0.0)
    if respect_robots_txt and session is not None:
        robots = _build_robots(
            seed,
            user_agent=user_agent,
            timeout=request_timeout,
            session=session,
        )
        # Honor robots.txt Crawl-delay: if the site asked us to wait longer
        # than the user's configured delay, use the site's value.
        if robots is not None:
            try:
                robots_delay = robots.crawl_delay(user_agent)
            except Exception:
                robots_delay = None
            if robots_delay:
                try:
                    effective_delay = max(effective_delay, float(robots_delay))
                except (TypeError, ValueError):
                    pass

    inc_re = re.compile(include_regex) if include_regex else None
    exc_re = re.compile(exclude_regex) if exclude_regex else None

    # BFS — (url, depth)
    queue: deque[tuple[str, int]] = deque([(seed, 0)])
    visited: set[str] = set()
    started = now()

    # If a seed body was supplied, treat the seed as already-fetched and seed
    # the frontier with the links extracted from it. We still enqueue the seed
    # in the visited set so we don't refetch it.
    seeded_from_body = False
    if seed_body is not None:
        visited.add(seed)
        result.urls.add(seed)
        result.pages_fetched += 1
        if "html" in (seed_content_type or "").lower():
            for raw_href in extractors.extract_from_html(seed_body, base_url=seed):
                canon = normalize.canonical_url(
                    raw_href, base_url=seed, **(normalize_opts or {})
                )
                if (
                    canon
                    and canon not in visited
                    and normalize.same_origin(canon, seed)
                    and (not inc_re or inc_re.search(canon))
                    and (not exc_re or not exc_re.search(canon))
                ):
                    result.urls.add(canon)
                    queue.append((canon, 1))
        seeded_from_body = True
        # Remove the original seed enqueue so we don't process it twice.
        if queue and queue[0] == (seed, 0):
            queue.popleft()

    while queue:
        if result.pages_fetched >= max_pages:
            result.hit_max_pages = True
            break
        if now() - started > time_budget_seconds:
            result.hit_time_budget = True
            break

        url, depth = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        # SSRF — every outbound URL is re-checked, not just the seed, because
        # links may point at hosts whose DNS resolves to private IP space.
        if not _ssrf_allowed(url):
            result.pages_skipped_ssrf += 1
            continue

        # robots
        if robots is not None and not robots.can_fetch(user_agent, url):
            result.pages_skipped_robots += 1
            continue

        # Space out requests (skip the delay if this is the first fetch of the
        # run AND we didn't already consume a "fetch" via the seed body).
        already_fetched = result.pages_fetched > (1 if seeded_from_body else 0)
        if already_fetched and effective_delay > 0:
            sleep(effective_delay)

        try:
            res = http_get(url, user_agent=user_agent, timeout=request_timeout)
        except Exception as exc:
            logger.debug(f"Crawl fetch failed for {url}: {exc!r}")
            result.pages_failed += 1
            continue

        # Support both 3-tuple (body, content_type, status) and legacy 2-tuple
        # (body, content_type) signatures so test hooks don't have to change.
        if len(res) == 3:
            body, content_type, status = res
        else:
            body, content_type = res
            status = None

        if body is None:
            # Non-2xx or blocked. Count as a failure so the warning heuristic
            # fires when a site is wall-to-wall forbidden.
            result.pages_failed += 1
            continue

        result.pages_fetched += 1
        result.urls.add(url)

        if depth >= max_depth:
            result.hit_max_depth = True
            continue

        if "html" not in (content_type or "").lower():
            continue

        for raw_href in extractors.extract_from_html(body, base_url=url):
            canon = normalize.canonical_url(raw_href, base_url=url, **(normalize_opts or {}))
            if not canon or canon in visited:
                continue
            if not normalize.same_origin(canon, seed):
                continue
            if inc_re and not inc_re.search(canon):
                continue
            if exc_re and exc_re.search(canon):
                continue
            result.urls.add(canon)
            queue.append((canon, depth + 1))

    # Post-run warning heuristic
    if result.failure_rate > FETCH_FAILURE_WARNING_THRESHOLD and (
        result.pages_fetched + result.pages_failed
    ) > 3:
        result.warnings.append(
            f"{result.pages_failed}/{result.pages_fetched + result.pages_failed} "
            f"fetches failed ({result.failure_rate:.0%}); inventory is likely incomplete."
        )
    if result.pages_skipped_ssrf:
        result.warnings.append(
            f"{result.pages_skipped_ssrf} URL(s) blocked by SSRF guard "
            f"(private/reserved IP ranges)."
        )

    return result


# ---------------------------------------------------------------------------
# Legacy aliases — kept so tests that monkey-patched the old name still work.
# ---------------------------------------------------------------------------

def _default_get(url: str, *, user_agent: str, timeout: float) -> tuple[Optional[str], str]:
    """Back-compat shim. New code uses :func:`_default_get_factory`."""
    session = requests.Session()
    body, ctype, _status = _default_get_factory(session)(
        url, user_agent=user_agent, timeout=timeout
    )
    return body, ctype
