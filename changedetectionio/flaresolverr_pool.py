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
