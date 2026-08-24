import hashlib
import os
from collections import OrderedDict
from urllib.parse import urlparse

from loguru import logger


class FlareSolverrException(Exception):
    pass


def get_flaresolverr_url():
    return os.getenv("FLARESOLVERR_URL", "").strip().strip('"').strip("'")


def is_flaresolverr_enabled():
    return bool(get_flaresolverr_url())


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

    def _ensure_url(self):
        if not self.flaresolverr_url:
            self.flaresolverr_url = get_flaresolverr_url()
        # Re-read dynamic envs
        self.max_sessions = get_flaresolverr_max_sessions()
        self.ttl_minutes = get_flaresolverr_ttl_minutes()
        self.timeout = get_flaresolverr_timeout()

    def _evict_if_needed(self):
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
        self._ensure_url()
        if not self.flaresolverr_url:
            return
        try:
            import requests

            payload = {"cmd": "sessions.destroy", "session": session_id}
            requests.post(self.flaresolverr_url, json=payload, timeout=5)
            logger.debug(f"Destroyed FlareSolverr session {session_id}")
        except Exception as e:
            logger.debug(f"Error destroying FlareSolverr session {session_id}: {e}")

    def clear(self):
        for _, data in list(self._lru.items()):
            try:
                self._destroy_session(data.get("session_id"))
            except Exception:
                pass
        self._lru.clear()

    def get_cached(self, url):
        host = _host_from_url(url)
        data = self._lru.get(host)
        if data:
            # move to end (most recent)
            self._lru.move_to_end(host)
        return data

    def solve(self, url, proxy_url=None, method="GET", post_data=None):
        self._ensure_url()
        if not self.flaresolverr_url:
            raise FlareSolverrException("FLARESOLVERR_URL not set")

        host = _host_from_url(url)
        # Check cache first? No, we always solve fresh but reuse session_id for warmth.
        # LRU handles session reuse.
        session_id = None
        if self.max_sessions > 0:
            # Reuse or create session_id for this host
            cached = self._lru.get(host)
            if cached:
                session_id = cached.get("session_id")
                self._lru.move_to_end(host)
            else:
                session_id = _session_id_for_host(host)
                # Evict before adding new host
                self._evict_if_needed()
                # Insert placeholder; will fill after solve
                self._lru[host] = {"session_id": session_id}
        else:
            # Ephemeral, no session
            session_id = None

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

        # Update LRU cache
        if self.max_sessions > 0 and host in self._lru:
            self._lru[host].update({"cookies": cookies, "userAgent": ua, "response": response_html})

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


def get_global_pool():
    global _global_pool
    if _global_pool is None:
        _global_pool = FlarePool()
    else:
        # Refresh env-driven settings
        _global_pool._ensure_url()
    return _global_pool
