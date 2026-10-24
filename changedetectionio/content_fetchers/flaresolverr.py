"""FlareSolverr overlay: solve challenges and feed the result into content fetchers.

Self-contained home for the overlay logic (per maintainer review) so it can
one day move to a plugin repo. Knows nothing about processors — callers pass
in plain data (watch, datastore, fetcher bits) and get back plain data.
"""
from loguru import logger


async def solve_flaresolverr(watch, datastore, url, proxy_url):
    """Solve the watch URL via FlareSolverr when effective, else None.

    Wraps get_flaresolverr_solution_for_watch() (env + global/per-watch
    toggle, POST body render, 1MB guard, shared-pool executor). Raises a
    plain Exception on solve failure so it lands in last_error like every
    other fetch failure.
    """
    try:
        from changedetectionio.flaresolverr_pool import get_flaresolverr_solution_for_watch

        return await get_flaresolverr_solution_for_watch(watch, datastore, proxy_url=proxy_url)
    except Exception as e:
        logger.error(f"FlareSolverr solve failed for {url}: {e}")
        raise Exception(f"FlareSolverr: {e}") from e


async def build_flaresolverr_bare_fetcher(solution, prefer_fetch_backend, fetcher_obj,
                                          proxy_url, custom_browser_connection_url,
                                          screenshot_format, worker_id, watch, datastore, url):
    """Serve a FlareSolverr solution.response directly (html_requests, no browser steps).

    Returns the populated fetcher (no browser launched), applying the same
    empty-page / non-200 semantics as the fetchers.
    """
    from changedetectionio.content_fetchers.exceptions import EmptyReply, Non200ErrorCodeReceived

    fetcher = fetcher_obj(proxy_override=proxy_url, custom_browser_connection_url=custom_browser_connection_url, screenshot_format=screenshot_format, worker_id=worker_id)
    fetcher.backend_name = prefer_fetch_backend + "+flaresolverr"
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
