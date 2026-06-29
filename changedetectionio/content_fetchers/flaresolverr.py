import asyncio
import os

from flask_babel import lazy_gettext as _l
from loguru import logger

from changedetectionio.content_fetchers.base import Fetcher
from changedetectionio.content_fetchers.exceptions import (
    BrowserConnectError,
    BrowserFetchTimedOut,
    BrowserStepsInUnsupportedFetcher,
    EmptyReply,
    Non200ErrorCodeReceived,
)


class fetcher(Fetcher):
    fetcher_description = _l(
        "FlareSolverr / Byparr - Cloudflare-aware solver "
        "(set FLARESOLVERR_URL env var, e.g. http://flaresolverr:8191/v1)"
    )

    # FlareSolverr drives its own browser server-side, so changedetection's
    # browser-step framework (which talks Playwright/CDP) cannot reach into it.
    supports_browser_steps = False
    supports_screenshots = False
    supports_xpath_element_data = False

    def __init__(self, proxy_override=None, custom_browser_connection_url=None, **kwargs):
        super().__init__(**kwargs)

        # Per-watch override wins (via the "Extra Browsers" connection URL field);
        # otherwise fall back to FLARESOLVERR_URL env var.
        if custom_browser_connection_url:
            self.browser_connection_is_custom = True
            self.browser_connection_url = custom_browser_connection_url.strip('"')
        else:
            self.browser_connection_url = os.getenv(
                "FLARESOLVERR_URL", "http://flaresolverr:8191/v1"
            ).strip('"')

        self.proxy_override = proxy_override

    def _post_command(self, payload, timeout):
        import requests

        try:
            r = requests.post(
                self.browser_connection_url,
                json=payload,
                timeout=timeout,
                headers={"Content-Type": "application/json"},
            )
        except requests.exceptions.Timeout as e:
            raise BrowserFetchTimedOut(msg=f"FlareSolverr request timed out after {timeout}s: {e}") from e
        except requests.exceptions.RequestException as e:
            raise BrowserConnectError(
                msg=f"Could not reach FlareSolverr at {self.browser_connection_url}: {e}"
            ) from e

        if r.status_code != 200:
            raise BrowserConnectError(
                msg=f"FlareSolverr returned HTTP {r.status_code}: {r.text[:300]}"
            )

        try:
            return r.json()
        except ValueError as e:
            raise BrowserConnectError(
                msg=f"FlareSolverr returned non-JSON response: {e}"
            ) from e

    def _run_sync(
        self,
        url,
        timeout,
        request_headers,
        request_body,
        request_method,
        ignore_status_codes=False,
        empty_pages_are_a_change=False,
    ):
        if self.browser_steps:
            raise BrowserStepsInUnsupportedFetcher(url=url)

        # FlareSolverr's /v1 endpoint expects milliseconds for maxTimeout.
        # `timeout` is in seconds at this layer (per the Fetcher contract).
        max_timeout_ms = int((timeout or 60) * 1000)

        # FlareSolverr supports only request.get and request.post on /v1.
        method = (request_method or "GET").upper()
        if method == "POST":
            payload = {
                "cmd": "request.post",
                "url": url,
                "maxTimeout": max_timeout_ms,
                # FlareSolverr expects form-encoded body as a single string
                "postData": request_body or "",
            }
        else:
            payload = {
                "cmd": "request.get",
                "url": url,
                "maxTimeout": max_timeout_ms,
            }
            if method != "GET":
                logger.warning(
                    f"FlareSolverr only supports GET/POST; coercing '{method}' to GET for {url}"
                )

        if self.proxy_override:
            # FlareSolverr accepts {"proxy": {"url": "...", "username": "...", "password": "..."}}.
            # changedetection passes the proxy as a single URL with optional creds embedded;
            # FlareSolverr's own client will parse the URL.
            payload["proxy"] = {"url": self.proxy_override}

        # Give the HTTP call a generous buffer over the solver's own deadline so
        # that we surface FlareSolverr's structured error instead of a connection abort.
        body = self._post_command(payload, timeout=(timeout or 60) + 30)

        if body.get("status") != "ok":
            raise BrowserConnectError(
                msg=f"FlareSolverr could not solve {url}: {body.get('message', 'unknown error')}"
            )

        solution = body.get("solution") or {}
        upstream_status = int(solution.get("status") or 0)
        html = solution.get("response") or ""

        self.headers = solution.get("headers") or {}
        self.status_code = upstream_status
        self.content = html
        self.raw_content = html.encode("utf-8", errors="replace")

        if not html:
            if not empty_pages_are_a_change:
                raise EmptyReply(url=url, status_code=upstream_status)
            logger.debug(
                f"FlareSolverr returned empty body for {url} (status {upstream_status}), "
                "but empty_pages_are_a_change=True"
            )

        if upstream_status != 200 and not ignore_status_codes:
            raise Non200ErrorCodeReceived(url=url, status_code=upstream_status, page_html=html)

    async def run(
        self,
        fetch_favicon=True,
        current_include_filters=None,
        empty_pages_are_a_change=False,
        ignore_status_codes=False,
        is_binary=False,
        request_body=None,
        request_headers=None,
        request_method=None,
        screenshot_format=None,
        timeout=None,
        url=None,
        watch_uuid=None,
    ):
        if is_binary:
            # FlareSolverr only returns rendered HTML; binary fetches should fall
            # back to html_requests at the caller. Surface a clear error.
            raise BrowserConnectError(
                msg="FlareSolverr fetcher does not support binary content; use html_requests."
            )

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._run_sync(
                url=url,
                timeout=timeout,
                request_headers=request_headers,
                request_body=request_body,
                request_method=request_method,
                ignore_status_codes=ignore_status_codes,
                empty_pages_are_a_change=empty_pages_are_a_change,
            ),
        )

    async def quit(self, watch=None):
        return

    def get_last_status_code(self):
        return self.status_code

    def is_ready(self):
        return bool(self.browser_connection_url)


class FlareSolverrFetcherPlugin:
    """Plugin class that registers the FlareSolverr fetcher as a built-in plugin."""

    def register_content_fetcher(self):
        return ("html_flaresolverr", fetcher)


flaresolverr_plugin = FlareSolverrFetcherPlugin()
