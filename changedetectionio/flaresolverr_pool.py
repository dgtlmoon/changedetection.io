import hashlib
import os
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from loguru import logger

# Dedicated executor for blocking FlareSolverr HTTP calls — avoids starving the loop's default executor
# which is also used by validate_fetch_url_async and other I/O. 5 workers is enough for 10 concurrent watches
# with 60s timeout without exhausting the default pool (min(32, cpu+4) ≈10).
FLARESOLVERR_EXECUTOR = ThreadPoolExecutor(max_workers=5, thread_name_prefix="FlareSolverr")


class FlareSolverrException(Exception):
    pass


def get_flaresolverr_url():
    return os.getenv("FLARESOLVERR_URL", "").strip().strip('"').strip("'")


def is_flaresolverr_enabled():
    url = get_flaresolverr_url()
    if not url:
        return False
    # Basic safety: must be http(s) and not file://, no backslash, valid URL — but allow private/docker DNS
    if "\\" in url:
        logger.warning(f"FLARESOLVERR_URL contains backslash — ignored: {url}")
        return False
    from changedetectionio.validate_url import is_safe_valid_url

    if not is_safe_valid_url(url):
        logger.warning(f"FLARESOLVERR_URL is not a safe http(s) URL: {url}")
        return False
    return True


def get_flaresolverr_max_sessions():
    try:
        return max(0, int(os.getenv("FLARESOLVERR_MAX_SESSIONS", "10")))
    except ValueError:
        return 10


def get_flaresolverr_timeout():
    try:
        return max(1, int(os.getenv("FLARESOLVERR_TIMEOUT", "60")))
    except ValueError:
        return 60


def get_flaresolverr_ttl_minutes():
    try:
        return max(1, int(os.getenv("FLARESOLVERR_TTL_MINUTES", "60")))
    except ValueError:
        return 60


def is_flaresolverr_effective(watch, datastore):
    if not is_flaresolverr_enabled():
        return False
    # Watch-level override: system | enabled | disabled
    val = (
        (watch.get("flaresolverr") or "system").lower()
        if isinstance(watch.get("flaresolverr"), str)
        else "system"
    )
    if val == "enabled":
        return True
    if val == "disabled":
        return False
    # system -> fallback to global
    # Support both application and requests locations for backwards compat
    global_enabled = datastore.data["settings"]["application"].get("flaresolverr_enabled")
    if global_enabled is None:
        global_enabled = datastore.data["settings"]["requests"].get("flaresolverr_enabled")
    return bool(global_enabled)


def _host_from_url(url):
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return url


def _session_id_for_host(host):
    h = hashlib.sha256(host.encode("utf-8")).hexdigest()[:12]
    return f"cdio-{h}"


def is_cookie_domain_valid(cookie_domain, host):
    """Validate cookie domain matches host to prevent session fixation via evil domain."""
    if not cookie_domain:
        return True  # No domain, will be scoped via url
    # Strip port from host
    host = host.split(":")[0].lower()
    domain = cookie_domain.lstrip(".").lower()
    if not domain:
        return False
    return host == domain or host.endswith("." + domain)


def normalize_flaresolverr_cookies(cookies, url):
    """Normalize and filter FlareSolverr cookies for browser injection.

    Shared helper to deduplicate cookie handling across Playwright,
    Puppeteer, Selenium and BrowserSteps. Validates domain against host,
    normalizes expires/sameSite, and scopes url-less cookies to *url*.

    Returns filtered list (may be empty). Logs warnings for drops.
    """
    if not cookies:
        return []
    host = urlparse(url).netloc.lower() if url else ""
    normalized = []
    for c in cookies:
        try:
            cc = dict(c)
        except Exception:
            continue
        domain = cc.get("domain")
        if domain and not is_cookie_domain_valid(domain, host):
            logger.warning(f"FlareSolverr cookie domain mismatch: {domain} vs host {host} — dropping")
            continue
        if "expires" in cc and isinstance(cc["expires"], (int, float)):
            try:
                cc["expires"] = float(cc["expires"])
            except Exception:
                cc.pop("expires", None)
        if "sameSite" in cc:
            v = cc.pop("sameSite")
            if isinstance(v, str) and v.capitalize() in ("Strict", "Lax", "None"):
                cc["sameSite"] = v.capitalize()
        if not cc.get("domain") and not cc.get("url") and url:
            cc["url"] = url
        normalized.append(cc)
    return normalized


async def inject_cookies_playwright(context, cookies, url, label="Playwright"):
    """Inject normalized FlareSolverr cookies into a Playwright context."""
    filtered = normalize_flaresolverr_cookies(cookies, url)
    if not filtered:
        if cookies:
            logger.warning(f"FlareSolverr no valid cookies to inject via {label}")
        return 0
    try:
        await context.add_cookies(filtered)
        logger.info(f"FlareSolverr injected {len(filtered)} cookies via {label}")
        return len(filtered)
    except Exception as e:
        logger.warning(f"FlareSolverr cookie inject failed ({label}): {e}")
        return 0


async def inject_cookies_puppeteer(page, cookies, url, label="Puppeteer"):
    """Inject normalized FlareSolverr cookies into a Puppeteer page."""
    filtered = normalize_flaresolverr_cookies(cookies, url)
    if not filtered:
        if cookies:
            logger.warning(f"FlareSolverr no valid cookies to inject via {label}")
        return 0
    try:
        await page.setCookie(*filtered)
        logger.info(f"FlareSolverr injected {len(filtered)} cookies via {label}")
        return len(filtered)
    except Exception as e:
        logger.warning(f"FlareSolverr cookie inject failed ({label}): {e}")
        return 0


def inject_cookies_selenium(driver, cookies, url, label="Selenium"):
    """Inject FlareSolverr cookies via Selenium WebDriver.

    Selenium cannot handle expires/sameSite the same way, so they are
    stripped and leading dots are removed from domain.
    """
    filtered = normalize_flaresolverr_cookies(cookies, url)
    if not filtered:
        if cookies:
            logger.warning(f"FlareSolverr no valid cookies to inject via {label}")
        return 0
    valid = 0
    for cc in filtered:
        # Selenium-specific tweaks
        cc = dict(cc)
        cc.pop("expires", None)
        cc.pop("sameSite", None)
        cc.pop("url", None)
        if cc.get("domain", "").startswith("."):
            cc["domain"] = cc["domain"].lstrip(".")
        try:
            driver.add_cookie(cc)
            valid += 1
        except Exception:
            pass
    if valid:
        logger.info(f"FlareSolverr injected {valid} cookies via {label}")
    else:
        logger.warning(f"FlareSolverr no valid cookies to inject via {label}")
    return valid


class FlarePool:
    def __init__(self, max_sessions=None, ttl_minutes=None, timeout=None, flaresolverr_url=None):
        self.max_sessions = (
            max_sessions if max_sessions is not None else get_flaresolverr_max_sessions()
        )
        self.ttl_minutes = (
            ttl_minutes if ttl_minutes is not None else get_flaresolverr_ttl_minutes()
        )
        self.timeout = timeout if timeout is not None else get_flaresolverr_timeout()
        self.flaresolverr_url = (
            flaresolverr_url if flaresolverr_url is not None else get_flaresolverr_url()
        )
        # host -> {session_id, cookies, userAgent, ts}
        self._lru = OrderedDict()
        self._lock = threading.RLock()

    def _ensure_url(self):
        # Re-read dynamic envs under lock? Called from within locked sections and also from get_global_pool
        with self._lock:
            if not self.flaresolverr_url:
                self.flaresolverr_url = get_flaresolverr_url()
            # Re-read dynamic envs
            self.max_sessions = get_flaresolverr_max_sessions()
            self.ttl_minutes = get_flaresolverr_ttl_minutes()
            self.timeout = get_flaresolverr_timeout()

    def _is_expired(self, entry):
        ts = entry.get("ts")
        if not ts:
            return False
        return (time.time() - ts) > (self.ttl_minutes * 60)

    def _evict_if_needed(self):
        with self._lock:
            # MAX=0 means ephemeral, no LRU at all — ensure empty
            if self.max_sessions == 0:
                # Clear any stale entries (should be empty, but defensive)
                for _, data in list(self._lru.items()):
                    try:
                        self._destroy_session(data.get("session_id"))
                    except Exception:
                        pass
                self._lru.clear()
                return
            while self.max_sessions > 0 and len(self._lru) >= self.max_sessions:
                old_host, old_data = self._lru.popitem(last=False)
                sid = old_data.get("session_id")
                logger.info(f"FlareSolverr LRU evict host {old_host} session {sid}")
                try:
                    self._destroy_session(sid)
                except Exception as e:
                    logger.debug(f"Failed to destroy evicted session {sid}: {e}")

    def _destroy_session(self, session_id):
        if not session_id:
            return
        # _ensure_url already handles lock
        url = self.flaresolverr_url or get_flaresolverr_url()
        if not url:
            return
        try:
            import requests

            payload = {"cmd": "sessions.destroy", "session": session_id}
            requests.post(url, json=payload, timeout=5)
            logger.debug(f"Destroyed FlareSolverr session {session_id}")
        except Exception as e:
            logger.debug(f"Error destroying FlareSolverr session {session_id}: {e}")

    def clear(self):
        with self._lock:
            for _, data in list(self._lru.items()):
                try:
                    self._destroy_session(data.get("session_id"))
                except Exception:
                    pass
            self._lru.clear()

    def get_cached(self, url):
        host = _host_from_url(url)
        with self._lock:
            data = self._lru.get(host)
            if data:
                if self._is_expired(data):
                    # Expired — evict
                    try:
                        self._destroy_session(data.get("session_id"))
                    except Exception:
                        pass
                    self._lru.pop(host, None)
                    return None
                # move to end (most recent)
                self._lru.move_to_end(host)
            return data

    def solve(self, url, proxy_url=None, method="GET", post_data=None):
        # SSRF gate for watch URL — defense in depth (processors/base already validates, but pool may be called from other paths)
        from changedetectionio.validate_url import is_fetch_url_allowed

        ok, reason = is_fetch_url_allowed(url)
        if not ok:
            raise FlareSolverrException(f"FlareSolverr blocked fetch URL: {reason}")
        # Guard against huge POST bodies being forwarded as amplification vector
        if post_data and len(post_data) > 1024 * 1024:
            logger.warning(f"FlareSolverr postData too large ({len(post_data)} bytes) for {url}, truncating to 1MB")
            post_data = post_data[:1024*1024]

        self._ensure_url()
        if not self.flaresolverr_url:
            raise FlareSolverrException("FLARESOLVERR_URL not set")

        host = _host_from_url(url)
        session_id = None
        with self._lock:
            if self.max_sessions == 0:
                session_id = None
            else:
                cached = self._lru.get(host)
                if cached and not self._is_expired(cached):
                    session_id = cached.get("session_id")
                    self._lru.move_to_end(host)
                elif cached and self._is_expired(cached):
                    try:
                        self._destroy_session(cached.get("session_id"))
                    except Exception:
                        pass
                    self._lru.pop(host, None)
                    cached = None
                if not cached:
                    session_id = _session_id_for_host(host)
                    self._evict_if_needed()
                    # Insert placeholder with ts; will fill after solve
                    self._lru[host] = {"session_id": session_id, "ts": time.time()}

        payload = {
            "cmd": f"request.{method.lower()}" if method.upper() == "POST" else "request.get",
            "url": url,
            "maxTimeout": self.timeout * 1000,
        }
        if session_id:
            payload["session"] = session_id
            payload["session_ttl_minutes"] = self.ttl_minutes
        if proxy_url:
            payload["proxy"] = {"url": proxy_url}
        if method.upper() == "POST" and post_data is not None:
            payload["postData"] = post_data

        logger.info(f"FlareSolverr solve host={host} session={session_id} url={url}")

        try:
            import requests

            resp = requests.post(self.flaresolverr_url, json=payload, timeout=self.timeout + 5)
        except Exception as e:
            raise FlareSolverrException(f"FlareSolverr request failed: {e}") from e

        try:
            data = resp.json()
        except Exception as e:
            raise FlareSolverrException(
                f"FlareSolverr invalid JSON: {e} status={resp.status_code}"
            ) from e

        status = data.get("status")
        message = data.get("message", "")
        solution = data.get("solution") or {}

        if status != "ok":
            # If session was used and challenge failed, destroy it so next try is fresh
            if session_id and self.max_sessions > 0:
                with self._lock:
                    try:
                        self._destroy_session(session_id)
                        self._lru.pop(host, None)
                    except Exception:
                        pass
            raise FlareSolverrException(f"FlareSolverr error status={status} msg={message}")

        cookies = solution.get("cookies") or []
        ua = solution.get("userAgent")
        response_html = solution.get("response") or ""
        resp_url = solution.get("url") or url
        resp_status = solution.get("status")

        # Validate we got at least cookies or response
        if not cookies and not response_html:
            raise FlareSolverrException(
                f"FlareSolverr empty solution status={status} msg={message}"
            )

        # Update LRU cache with ts
        if self.max_sessions > 0:
            with self._lock:
                if host in self._lru:
                    self._lru[host].update({"cookies": cookies, "userAgent": ua, "response": response_html, "ts": time.time()})
                    self._lru.move_to_end(host)

        return {
            "cookies": cookies,
            "userAgent": ua,
            "response": response_html,
            "url": resp_url,
            "status": resp_status,
            "headers": solution.get("headers") or {},
            "session_id": session_id,
        }


# Global singleton shared between A and C paths
_global_pool = None
_global_pool_lock = threading.Lock()


def get_global_pool():
    global _global_pool
    with _global_pool_lock:
        if _global_pool is None:
            _global_pool = FlarePool()
        else:
            # Refresh env-driven settings
            _global_pool._ensure_url()
        return _global_pool


def resolve_flaresolverr_user_agent(flaresolverr_user_agent, headers=None):
    """Resolve UA for browser contexts — FlareSolverr UA wins, else manage_user_agent."""
    if flaresolverr_user_agent:
        return flaresolverr_user_agent
    # Lazy import to avoid circular deps (base -> validate_url, content_fetchers -> flaresolverr_pool)
    try:
        from changedetectionio.content_fetchers.base import manage_user_agent

        return manage_user_agent(headers=headers)
    except Exception:
        return None


async def apply_flaresolverr_user_agent_puppeteer(page, flaresolverr_user_agent, request_headers):
    """Apply FlareSolverr UA or header UA to a Puppeteer page, returning filtered headers.

    Handles User-Agent header deduplication: when UA is set via setUserAgent,
    the corresponding header is removed from extra_http_headers to avoid
    conflicting values. Returns (filtered_headers) dict to use for setExtraHTTPHeaders.
    """
    headers_copy = dict(request_headers) if request_headers else {}
    try:
        from changedetectionio.content_fetchers.base import manage_user_agent
    except Exception:
        manage_user_agent = None

    if flaresolverr_user_agent:
        try:
            await page.setUserAgent(flaresolverr_user_agent)
        except Exception:
            pass
        headers_copy.pop("User-Agent", None)
        headers_copy.pop("user-agent", None)
    else:
        user_agent = None
        if headers_copy.get("User-Agent"):
            user_agent = headers_copy.pop("User-Agent").strip()
            try:
                await page.setUserAgent(user_agent)
            except Exception:
                pass
        elif headers_copy.get("user-agent"):
            user_agent = headers_copy.pop("user-agent").strip()
            try:
                await page.setUserAgent(user_agent)
            except Exception:
                pass
        if not user_agent and manage_user_agent:
            try:
                current_ua = await page.evaluate("navigator.userAgent")
            except Exception:
                current_ua = None
            ua = manage_user_agent(headers=headers_copy, current_ua=current_ua)
            if ua:
                try:
                    await page.setUserAgent(ua)
                except Exception:
                    pass
    return headers_copy


async def async_flaresolverr_solve(url, proxy_url=None, method="GET", post_data=None):
    """Async wrapper that runs blocking FlarePool.solve in FLARESOLVERR_EXECUTOR."""
    import asyncio

    pool = get_global_pool()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        FLARESOLVERR_EXECUTOR, lambda: pool.solve(url, proxy_url=proxy_url, method=method, post_data=post_data)
    )


async def get_flaresolverr_solution_for_watch(watch, datastore, proxy_url=None, url_override=None):
    """Shared helper for processors/base and browser_steps live UI.

    - Checks is_flaresolverr_effective(watch, datastore)
    - Renders POST body via jinja2 (watch.get('body')), truncates to 1MB
    - Calls async_flaresolverr_solve with correct method/post_data
    Returns solution dict or None if not effective. Raises FlareSolverrException on failure.
    """
    if not is_flaresolverr_effective(watch, datastore):
        return None
    url = url_override or watch.link
    method = (watch.get("method") or "GET").upper()
    body = watch.get("body")
    if body:
        try:
            from changedetectionio.jinja2_custom import render as jinja_render

            body = jinja_render(template_str=body)
        except Exception:
            pass
        if body and len(body) > 1024 * 1024:
            logger.warning(f"FlareSolverr POST body too large ({len(body)} bytes), truncating to 1MB for {url}")
            body = body[:1024 * 1024]
    post_data = body if method == "POST" else None
    solution = await async_flaresolverr_solve(url, proxy_url=proxy_url, method=method, post_data=post_data)
    try:
        host = urlparse(url).netloc
    except Exception:
        host = url
    logger.info(f"FlareSolverr solved {url} host={host} via session {solution.get('session_id')}")
    return solution
