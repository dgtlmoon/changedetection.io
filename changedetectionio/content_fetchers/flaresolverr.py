"""FlareSolverr overlay: solve challenges and feed the result into content fetchers.

Self-contained home for the overlay logic (per maintainer review) so it can
one day move to a plugin repo. Knows nothing about processors — callers pass
in plain data (watch, datastore, fetcher bits) and get back plain data.
"""
from loguru import logger


async def solve_for_watch(watch, datastore, url, proxy_url=None, timeout=None):
    """Solve the watch URL via FlareSolverr when effective, else None.

    Returns (solution, cookies, user_agent): the raw daemon solution plus
    cookies normalized once for browser injection (domain-checked against
    *url*, url-scoped) and the solved UA (or None) — ready for the generic
    cookies=/headers= fetcher channels, so callers never touch
    flaresolverr specifics. Raises a plain Exception on solve failure so it
    lands in last_error like every other fetch failure. *timeout* bounds the
    whole solve when set; otherwise the daemon maxTimeout + client timeout
    bound it.
    """
    import asyncio

    try:
        from changedetectionio.flaresolverr_pool import (
            get_flaresolverr_solution_for_watch,
            normalize_flaresolverr_cookies,
        )

        async def _solve():
            return await get_flaresolverr_solution_for_watch(watch, datastore, proxy_url=proxy_url)

        solution = await asyncio.wait_for(_solve(), timeout) if timeout else await _solve()
    except Exception as e:
        logger.error(f"FlareSolverr solve failed for {url}: {e}")
        raise Exception(f"FlareSolverr: {e}") from e
    if solution is None:
        return None
    cookies = normalize_flaresolverr_cookies(solution.get('cookies'), url)
    if solution.get('cookies') and not cookies:
        logger.warning(f"FlareSolverr no valid cookies to inject for {url}")
    return solution, cookies, solution.get('userAgent')


def stamp_backend_name(prefer_fetch_backend, solved):
    """Backend stamp for the overlay (e.g. html_requests+flaresolverr)."""
    return prefer_fetch_backend + ("+flaresolverr" if solved else "")


# Browser backends whose fetcher speaks the generic cookies=/headers= channels.
# Anything else (e.g. a plugin fetcher that never learned them) gets a normal
# fetch — fail closed instead of silently dropping the challenge context.
_HYBRID_BACKENDS = frozenset(["html_webdriver"])


def decide_challenge_route(prefer_fetch_backend, has_browser_steps):
    """Where a solved challenge may go: "bare", "hybrid" or "skip".

    Bare serves solution.response directly (html_requests, no browser steps).
    Hybrid replays cookies/UA in the fetching browser. Unknown backends skip
    the overlay entirely — the watch is fetched normally.
    """
    if prefer_fetch_backend == "html_requests" and not has_browser_steps:
        return "bare"
    if prefer_fetch_backend in _HYBRID_BACKENDS:
        return "hybrid"
    return "skip"


# Backends already warned about (log-once per backend: every check is noise)
_warned_skip_backends = set()


def warn_challenge_skipped(url, prefer_fetch_backend, has_browser_steps):
    """Log-once explanation for a skipped overlay (fail-closed to normal fetch)."""
    key = (prefer_fetch_backend, has_browser_steps)
    if key in _warned_skip_backends:
        return
    _warned_skip_backends.add(key)
    if prefer_fetch_backend == "html_requests" and has_browser_steps:
        logger.warning(f"Challenge-solver overlay skipped for {url}: "
                       f"browser steps need a browser backend, not html_requests — fetching normally")
    else:
        logger.warning(f"Challenge-solver overlay skipped for {url}: "
                       f"backend '{prefer_fetch_backend}' can't consume challenge context "
                       f"(only html_requests/html_webdriver supported) — fetching normally")


async def build_flaresolverr_bare_fetcher(solution, prefer_fetch_backend, fetcher_obj,
                                          proxy_url, custom_browser_connection_url,
                                          screenshot_format, worker_id, watch, datastore, url):
    """Serve a FlareSolverr solution.response directly (html_requests, no browser steps).

    Returns the populated fetcher (no browser launched), applying the same
    empty-page / non-200 semantics as the fetchers.
    """
    from changedetectionio.content_fetchers.exceptions import EmptyReply, Non200ErrorCodeReceived

    fetcher = fetcher_obj(proxy_override=proxy_url, custom_browser_connection_url=custom_browser_connection_url, screenshot_format=screenshot_format, worker_id=worker_id)
    fetcher.backend_name = stamp_backend_name(prefer_fetch_backend, True)
    _resp = solution.get('response') or ''
    _status = solution.get('status') or 200
    _headers = solution.get('headers')
    if not isinstance(_headers, dict):
        _headers = {}
    fetcher.content = _resp
    fetcher.raw_content = _resp.encode('utf-8') if isinstance(_resp, str) else _resp
    fetcher.status_code = _status
    fetcher.headers = _headers
    _empty_pages_are_a_change = datastore.data['settings']['application'].get('empty_pages_are_a_change', False)
    _ignore_status_codes = watch.get('ignore_status_codes', False)
    if not _resp or not len(_resp.strip()):
        if not _empty_pages_are_a_change:
            raise EmptyReply(url=url, status_code=_status)
    if _status != 200 and not _ignore_status_codes:
        raise Non200ErrorCodeReceived(url=url, status_code=_status, page_html=_resp)
    await fetcher.quit(watch=watch)
    if fetcher.content and isinstance(fetcher.content, str):
        fetcher.content = fetcher.content.encode('utf-8', errors='replace').decode('utf-8')
    return fetcher
