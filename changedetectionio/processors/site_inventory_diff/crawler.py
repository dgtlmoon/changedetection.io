"""
Bounded same-origin crawler for the site_inventory_diff processor.

Design goals:

* Bounded in every dimension — max pages, max depth, overall budget in seconds.
* Well-behaved — obeys robots.txt by default, spaces requests by a user-set
  delay, sends a clear User-Agent (onChange-Inventory/<version>).
* Same-origin only — follows links that share a registrable host with the seed.
* Deterministic — BFS with sorted frontier, so snapshot ordering is stable.

The crawler is intentionally self-contained (``requests``-only, no Playwright).
For most URL-inventory use cases a full browser is overkill; users who need JS
rendering can still use the sitemap or listing-page modes with any fetcher.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Iterable, Optional
from urllib import robotparser
from urllib.parse import urlsplit

import requests
from loguru import logger

from . import extractors
from . import normalize


# Conservative default — every request carries an identifying UA so site
# operators can contact us / rate-limit us gracefully.
DEFAULT_USER_AGENT = "onChange-Inventory-Crawler/1.0 (+https://change.sairo.app)"


class CrawlResult:
    """Accumulated crawler output.

    Attributes:
        urls: Canonicalized URLs discovered.
        pages_fetched: Number of pages actually fetched (200-class).
        pages_skipped_robots: Pages skipped because robots.txt disallowed.
        hit_max_pages: True if the ``max_pages`` cap was reached.
        hit_max_depth: True if any link was skipped due to ``max_depth``.
        hit_time_budget: True if ``time_budget_seconds`` was exhausted.
        warnings: Human-readable warnings to surface in the snapshot header.
    """

    __slots__ = (
        "urls",
        "pages_fetched",
        "pages_skipped_robots",
        "hit_max_pages",
        "hit_max_depth",
        "hit_time_budget",
        "warnings",
    )

    def __init__(self) -> None:
        self.urls: set[str] = set()
        self.pages_fetched = 0
        self.pages_skipped_robots = 0
        self.hit_max_pages = False
        self.hit_max_depth = False
        self.hit_time_budget = False
        self.warnings: list[str] = []


def _build_robots(seed_url: str, user_agent: str, timeout: float) -> Optional[robotparser.RobotFileParser]:
    """Load robots.txt for the seed's host; return None on any failure."""
    parts = urlsplit(seed_url)
    if not parts.scheme or not parts.hostname:
        return None
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    rp = robotparser.RobotFileParser()
    try:
        resp = requests.get(
            robots_url,
            headers={"User-Agent": user_agent},
            timeout=timeout,
            allow_redirects=True,
        )
        if 200 <= resp.status_code < 300 and resp.text:
            rp.parse(resp.text.splitlines())
            return rp
    except requests.RequestException as exc:
        logger.debug(f"robots.txt fetch failed for {robots_url}: {exc!r}")
    # Missing robots.txt means "allow all"; represent that with an empty parser.
    rp.parse([])
    return rp


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
    _now: Optional[callable] = None,
    _sleep: Optional[callable] = None,
    _get: Optional[callable] = None,
) -> CrawlResult:
    """Run a bounded same-origin crawl starting from ``seed_url``.

    The last three underscore-prefixed args are test hooks — ``_now`` and
    ``_sleep`` let tests inject a fake clock, and ``_get`` lets them swap the
    HTTP client.
    """
    import re

    now = _now or time.monotonic
    sleep = _sleep or time.sleep
    http_get = _get or _default_get

    result = CrawlResult()

    seed = normalize.canonical_url(seed_url, **(normalize_opts or {}))
    if not seed:
        result.warnings.append(f"Invalid seed URL: {seed_url!r}")
        return result

    robots: Optional[robotparser.RobotFileParser] = None
    if respect_robots_txt:
        robots = _build_robots(seed, user_agent=user_agent, timeout=request_timeout)

    inc_re = re.compile(include_regex) if include_regex else None
    exc_re = re.compile(exclude_regex) if exclude_regex else None

    # BFS — (url, depth)
    queue: deque[tuple[str, int]] = deque([(seed, 0)])
    visited: set[str] = set()
    started = now()

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

        # robots
        if robots is not None and not robots.can_fetch(user_agent, url):
            result.pages_skipped_robots += 1
            continue

        # Space out requests
        if result.pages_fetched > 0 and crawl_delay_seconds > 0:
            sleep(crawl_delay_seconds)

        try:
            body, content_type = http_get(url, user_agent=user_agent, timeout=request_timeout)
        except Exception as exc:
            logger.debug(f"Crawl fetch failed for {url}: {exc!r}")
            continue

        if body is None:
            continue
        result.pages_fetched += 1
        result.urls.add(url)

        if depth >= max_depth:
            result.hit_max_depth = True
            continue

        # Parse anchors; ignore non-HTML responses.
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

    return result


def _default_get(url: str, *, user_agent: str, timeout: float) -> tuple[Optional[str], str]:
    """Default HTTP GET used by :func:`crawl`. Returns ``(body, content_type)``.

    Separated out so tests can monkeypatch it via the ``_get`` hook. Kept tiny
    and synchronous — the crawler is bounded anyway.
    """
    resp = requests.get(
        url,
        headers={"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml"},
        timeout=timeout,
        allow_redirects=True,
    )
    if not (200 <= resp.status_code < 300):
        return None, resp.headers.get("Content-Type", "")
    # Use response.text which handles encoding.
    return resp.text, resp.headers.get("Content-Type", "")
