import hashlib
import math
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


def _check_post_data_size(url, post_data):
    """Reject oversized POST bodies by WIRE size.

    Truncating would silently corrupt form/JSON payloads and store a wrong
    comparison baseline, so refuse loudly instead of forwarding a cut payload.
    """
    if not post_data:
        return post_data
    size = len(post_data.encode("utf-8")) if isinstance(post_data, str) else len(post_data)
    if size > 1024 * 1024:
        raise FlareSolverrException(
            f"FlareSolverr POST body too large ({size} bytes) for {url} — refusing to forward a truncated payload"
        )
    return post_data


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
    """Hostname for LRU keys and cookie checks — no userinfo/port/brackets."""
    try:
        hostname = urlparse(url).hostname
        return hostname.lower() if hostname else url
    except Exception:
        return url


def _session_id_for_host(host):
    h = hashlib.sha256(host.encode("utf-8")).hexdigest()[:12]
    return f"cdio-{h}"


def is_cookie_domain_valid(cookie_domain, host):
    """Validate cookie domain matches host to prevent session fixation via evil domain.

    Both sides are expected as plain hostnames (see _host_from_url); comparison
    is case-insensitive, dot-trimmed and IDNA-normalized. An exact match always
    wins (harmless, e.g. localhost); suffix matches require a multi-label
    domain so a bare "com" can never scope a cookie to every .com host.
    Multi-label public suffixes (co.uk) still match — distinguishing those
    needs a PSL; browsers refuse to store cookies on public suffixes anyway,
    and our contexts are single-use.
    """
    if not cookie_domain:
        return True  # No domain, will be scoped via url
    if not isinstance(cookie_domain, str) or not isinstance(host, str):
        return False
    domain = cookie_domain.lstrip(".").rstrip(".").lower()
    host = host.rstrip(".").lower()
    try:
        domain = domain.encode("idna").decode("ascii")
        host = host.encode("idna").decode("ascii")
    except Exception:
        return False
    if not domain:
        return False
    if host == domain:
        return True
    if "." not in domain:
        return False
    return host.endswith("." + domain)


def normalize_flaresolverr_cookies(cookies, url):
    """Normalize and filter FlareSolverr cookies for browser injection.

    Shared helper to deduplicate cookie handling across Playwright,
    Puppeteer, Selenium and BrowserSteps. Validates domain against host,
    normalizes expires/sameSite, and scopes url-less cookies to *url*.

    Returns filtered list (may be empty). Logs warnings for drops.
    """
    if not cookies:
        return []
    try:
        host = urlparse(url).hostname if url else ""
    except Exception:
        host = ""
    host = (host or "").lower()
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
        if "expires" in cc:
            try:
                v = float(cc["expires"])
                if not math.isfinite(v):
                    raise ValueError("expires must be finite")
                cc["expires"] = v
            except (TypeError, ValueError, OverflowError):
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
        # Explicit constructor args win over env on every solve() — _ensure_url()
        # only refreshes values that were left as None (the global pool passes
        # all None so it keeps tracking env).
        self._explicit = {
            name
            for name, value in (
                ("max_sessions", max_sessions),
                ("ttl_minutes", ttl_minutes),
                ("timeout", timeout),
                ("flaresolverr_url", flaresolverr_url),
            )
            if value is not None
        }
        # host -> {session_id, cookies, userAgent, ts}
        self._lru = OrderedDict()
        self._lock = threading.RLock()

    def _ensure_url(self):
        # Refresh env-driven settings. Re-entrant (RLock): also called from
        # get_global_pool, and _acquire_session takes the same lock.
        with self._lock:
            if "flaresolverr_url" not in self._explicit:
                self.flaresolverr_url = get_flaresolverr_url()
            # Re-read dynamic envs, unless explicitly pinned via the constructor
            if "max_sessions" not in self._explicit:
                self.max_sessions = get_flaresolverr_max_sessions()
            if "ttl_minutes" not in self._explicit:
                self.ttl_minutes = get_flaresolverr_ttl_minutes()
            if "timeout" not in self._explicit:
                self.timeout = get_flaresolverr_timeout()

    def _is_expired(self, entry):
        ts = entry.get("ts")
        if not ts:
            # No timestamp means unknown age — fail closed and treat as expired
            return True
        return (time.time() - ts) > (self.ttl_minutes * 60)

    def _acquire_session(self, host):
        """LRU bookkeeping under lock. Returns (session_id, stale_ids, settings).

        The caller destroys stale_ids OUTSIDE the lock — destroying is
        network I/O and must never run while holding it. settings is a
        snapshot of the env-driven values so one solve() stays on a
        consistent view even if another thread refreshes mid-flight.
        """
        stale = []
        with self._lock:
            settings = {
                "max_sessions": self.max_sessions,
                "ttl_minutes": self.ttl_minutes,
                "timeout": self.timeout,
                "flaresolverr_url": self.flaresolverr_url,
            }
            if self.max_sessions == 0:
                # Ephemeral mode — drop everything, keep no LRU at all
                for _, data in self._lru.items():
                    if data.get("session_id"):
                        stale.append(data.get("session_id"))
                self._lru.clear()
                return None, stale, settings
            cached = self._lru.get(host)
            if cached and not self._is_expired(cached):
                self._lru.move_to_end(host)
                return cached.get("session_id"), stale, settings
            if cached:
                # Expired — drop it, destroy outside
                if cached.get("session_id"):
                    stale.append(cached.get("session_id"))
                self._lru.pop(host, None)
            session_id = _session_id_for_host(host)
            while self.max_sessions > 0 and len(self._lru) >= self.max_sessions:
                old_host, old_data = self._lru.popitem(last=False)
                logger.info(f"FlareSolverr LRU evict host {old_host} session {old_data.get('session_id')}")
                if old_data.get("session_id"):
                    stale.append(old_data.get("session_id"))
            # Insert placeholder with ts; filled after a successful solve
            self._lru[host] = {"session_id": session_id, "ts": time.time()}
            return session_id, stale, settings

    def _destroy_session(self, session_id):
        if not session_id:
            return
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
            stale = [d.get("session_id") for d in self._lru.values() if d.get("session_id")]
            self._lru.clear()
        for sid in stale:
            self._destroy_session(sid)

    def get_cached(self, url):
        host = _host_from_url(url)
        stale_id = None
        with self._lock:
            data = self._lru.get(host)
            if data:
                if self._is_expired(data):
                    # Expired — evict (destroyed outside the lock below)
                    stale_id = data.get("session_id")
                    self._lru.pop(host, None)
                    data = None
                else:
                    # move to end (most recent)
                    self._lru.move_to_end(host)
        if stale_id:
            self._destroy_session(stale_id)
        return data

    def _post_solution(self, url, host, session_id, payload, settings, destroyed):
        """POST the payload and validate the solution dict.

        Any failure pops the LRU placeholder so the next solve() starts
        fresh instead of reusing a poisoned session. Challenge failures
        additionally destroy the session server-side — unless it was
        already destroyed as stale during this same solve().
        settings is the _acquire_session() snapshot; destroyed the set of
        session ids already destroyed by the caller.
        """
        try:
            import requests

            resp = requests.post(settings["flaresolverr_url"], json=payload,
                                 timeout=settings["timeout"] + 5)
        except Exception as e:
            with self._lock:
                self._lru.pop(host, None)
            raise FlareSolverrException(f"FlareSolverr request failed: {e}") from e

        try:
            data = resp.json()
        except Exception as e:
            with self._lock:
                self._lru.pop(host, None)
            raise FlareSolverrException(
                f"FlareSolverr invalid JSON: {e} status={resp.status_code}"
            ) from e

        status = data.get("status")
        message = data.get("message", "")
        solution = data.get("solution") or {}

        if status != "ok":
            # If session was used and challenge failed, destroy it so next try is fresh.
            # Skip ones already destroyed as stale above — same deterministic id.
            with self._lock:
                self._lru.pop(host, None)
            if session_id and session_id not in destroyed and settings["max_sessions"] > 0:
                self._destroy_session(session_id)
                destroyed.add(session_id)
            raise FlareSolverrException(f"FlareSolverr error status={status} msg={message}")

        # Validate we got at least cookies or response. Unlike a challenge
        # failure above, the session itself is probably fine here (only the
        # content is missing), so pop the placeholder but do NOT destroy —
        # the next solve() reuses the same deterministic session id.
        if not solution.get("cookies") and not solution.get("response"):
            with self._lock:
                self._lru.pop(host, None)
            raise FlareSolverrException(
                f"FlareSolverr empty solution status={status} msg={message}"
            )
        return solution

    def solve(self, url, proxy_url=None, method="GET", post_data=None):
        # SSRF gate for watch URL — defense in depth (processors/base already validates, but pool may be called from other paths)
        from changedetectionio.validate_url import is_fetch_url_allowed

        ok, reason = is_fetch_url_allowed(url)
        if not ok:
            raise FlareSolverrException(f"FlareSolverr blocked fetch URL: {reason}")
        # Guard against huge POST bodies being forwarded as amplification vector
        post_data = _check_post_data_size(url, post_data)

        self._ensure_url()

        host = _host_from_url(url)
        session_id, stale, settings = self._acquire_session(host)
        destroyed = set()
        for sid in stale:
            self._destroy_session(sid)
            destroyed.add(sid)
        if not settings["flaresolverr_url"]:
            raise FlareSolverrException("FLARESOLVERR_URL not set")

        payload = {
            "cmd": f"request.{method.lower()}" if method.upper() == "POST" else "request.get",
            "url": url,
            "maxTimeout": settings["timeout"] * 1000,
        }
        if session_id:
            payload["session"] = session_id
            payload["session_ttl_minutes"] = settings["ttl_minutes"]
        if proxy_url:
            payload["proxy"] = {"url": proxy_url}
        if method.upper() == "POST" and post_data is not None:
            payload["postData"] = post_data

        logger.info(f"FlareSolverr solve host={host} session={session_id} url={url}")

        solution = self._post_solution(url, host, session_id, payload, settings, destroyed)

        cookies = solution.get("cookies") or []
        ua = solution.get("userAgent")
        response_html = solution.get("response") or ""
        resp_url = solution.get("url") or url
        resp_status = solution.get("status")

        # Update LRU cache with ts
        if settings["max_sessions"] > 0:
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
    # Plain dict copy (never mutate the caller's headers); the UA key lookup
    # is case-insensitive but all other keys keep their original casing.
    headers_copy = dict(request_headers) if request_headers else {}
    try:
        from changedetectionio.content_fetchers.base import manage_user_agent
    except Exception:
        manage_user_agent = None

    # All UA header spellings — a dict could carry both "User-Agent" and
    # "user-agent"; leaving any of them would send a conflicting value.
    ua_keys = [k for k in list(headers_copy) if isinstance(k, str) and k.lower() == "user-agent"]
    if flaresolverr_user_agent:
        try:
            await page.setUserAgent(flaresolverr_user_agent)
        except Exception:
            pass
        for k in ua_keys:
            headers_copy.pop(k, None)
    else:
        user_agent = None
        for k in ua_keys:
            v = headers_copy.pop(k)
            if user_agent is None and isinstance(v, str) and v.strip():
                user_agent = v.strip()
        if user_agent:
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


async def get_flaresolverr_solution_for_watch(watch, datastore, proxy_url=None):
    """Shared helper for processors/base and browser_steps live UI.

    - Checks is_flaresolverr_effective(watch, datastore)
    - Renders POST body via jinja2 (watch.get('body')), rejects >1MB
    - Calls async_flaresolverr_solve with correct method/post_data
    Returns solution dict or None if not effective. Raises FlareSolverrException on failure.
    """
    if not is_flaresolverr_effective(watch, datastore):
        return None
    url = watch.link
    method = (watch.get("method") or "GET").upper()
    body = watch.get("body")
    if body:
        try:
            from changedetectionio.jinja2_custom import render as jinja_render

            body = jinja_render(template_str=body)
        except Exception:
            pass
        body = _check_post_data_size(url, body)
    post_data = body if method == "POST" else None
    solution = await async_flaresolverr_solve(url, proxy_url=proxy_url, method=method, post_data=post_data)
    host = _host_from_url(url)
    logger.info(f"FlareSolverr solved {url} host={host} via session {solution.get('session_id')}")
    return solution
