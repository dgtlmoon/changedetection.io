#!/usr/bin/env python3
"""Unit tests for the FlareSolverr overlay (changedetectionio/flaresolverr_pool.py).

No network, no daemon, no browser: the URL gate and requests.post are mocked,
browser APIs are faked with AsyncMock/MagicMock. Mirrors the pattern of
tests/unit/test_fetch_url_gate.py — pin the security-relevant behavior
(domain validation, SSRF gate, POST size guard) so a future refactor is the
only way to regress it.
"""

import asyncio
import re
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from changedetectionio.content_fetchers.exceptions import EmptyReply, Non200ErrorCodeReceived
from changedetectionio.content_fetchers.flaresolverr import build_flaresolverr_bare_fetcher, solve_flaresolverr
from changedetectionio.flaresolverr_pool import (
    FlarePool,
    FlareSolverrException,
    apply_flaresolverr_user_agent_puppeteer,
    get_flaresolverr_solution_for_watch,
    inject_cookies_playwright,
    inject_cookies_puppeteer,
    inject_cookies_selenium,
    is_cookie_domain_valid,
    is_flaresolverr_effective,
    is_flaresolverr_enabled,
    normalize_flaresolverr_cookies,
    resolve_flaresolverr_user_agent,
)

FLARESOLVERR_ENV = {"FLARESOLVERR_URL": "http://flaresolverr:8191/v1"}
WATCH_URL = "https://www.example.com/page"


class FakeWatch(dict):
    """Minimal watch stub: attribute access for .link, dict .get() for the rest.

    Note: real Watch.link Jinja-renders the URL and can yield DISABLED /
    source: handling; this stub returns the raw value, so those paths are
    out of scope here.
    """

    @property
    def link(self):
        return self.get("link")


def make_datastore(application_enabled=None, requests_enabled=None):
    return SimpleNamespace(
        data={"settings": {"application": {"flaresolverr_enabled": application_enabled},
                           "requests": {"flaresolverr_enabled": requests_enabled}}}
    )


def make_solution(cookies=None, user_agent="FlareUA/1.0", response="<html>ok</html>", status=200,
                  headers=None):
    return {
        "cookies": cookies if cookies is not None else [{"name": "cf_clearance", "value": "abc",
                                                          "domain": "example.com", "path": "/"}],
        "userAgent": user_agent,
        "response": response,
        "url": WATCH_URL,
        "status": status,
        "headers": headers if headers is not None else {},
        "session_id": "cdio-test",
    }


class FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def gate_allowed(url):
    return (True, "")


class TestIsFlareSolverrEnabled:
    def test_disabled_without_env(self):
        with patch.dict("os.environ", {"FLARESOLVERR_URL": ""}):
            assert is_flaresolverr_enabled() is False

    def test_enabled_with_valid_url(self):
        with patch.dict("os.environ", FLARESOLVERR_ENV):
            assert is_flaresolverr_enabled() is True

    def test_rejects_file_url(self):
        with patch.dict("os.environ", {"FLARESOLVERR_URL": "file:///etc/passwd"}):
            assert is_flaresolverr_enabled() is False

    def test_rejects_backslash(self):
        with patch.dict("os.environ", {"FLARESOLVERR_URL": "http://flaresolverr:8191\\v1"}):
            assert is_flaresolverr_enabled() is False


class TestIsFlareSolverrEffective:
    def test_system_follows_global_on(self):
        with patch.dict("os.environ", FLARESOLVERR_ENV):
            assert is_flaresolverr_effective(FakeWatch({"flaresolverr": "system"}),
                                             make_datastore(application_enabled=True)) is True

    def test_system_follows_global_off(self):
        with patch.dict("os.environ", FLARESOLVERR_ENV):
            assert is_flaresolverr_effective(FakeWatch({"flaresolverr": "system"}),
                                             make_datastore(application_enabled=False)) is False

    def test_enabled_overrides_global_off(self):
        with patch.dict("os.environ", FLARESOLVERR_ENV):
            assert is_flaresolverr_effective(FakeWatch({"flaresolverr": "enabled"}),
                                             make_datastore(application_enabled=False)) is True

    def test_disabled_overrides_global_on(self):
        with patch.dict("os.environ", FLARESOLVERR_ENV):
            assert is_flaresolverr_effective(FakeWatch({"flaresolverr": "disabled"}),
                                             make_datastore(application_enabled=True)) is False

    def test_env_unset_disables_everything(self):
        with patch.dict("os.environ", {"FLARESOLVERR_URL": ""}):
            assert is_flaresolverr_effective(FakeWatch({"flaresolverr": "enabled"}),
                                             make_datastore(application_enabled=True)) is False

    def test_requests_location_fallback_on(self):
        with patch.dict("os.environ", FLARESOLVERR_ENV):
            assert is_flaresolverr_effective(FakeWatch({}),
                                             make_datastore(application_enabled=None,
                                                            requests_enabled=True)) is True

    def test_requests_location_fallback_off(self):
        with patch.dict("os.environ", FLARESOLVERR_ENV):
            assert is_flaresolverr_effective(FakeWatch({}),
                                             make_datastore(application_enabled=None,
                                                            requests_enabled=False)) is False

    def test_non_string_value_treated_as_system(self):
        with patch.dict("os.environ", FLARESOLVERR_ENV):
            assert is_flaresolverr_effective(FakeWatch({"flaresolverr": True}),
                                             make_datastore(application_enabled=True)) is True

    def test_missing_key_follows_global(self):
        with patch.dict("os.environ", FLARESOLVERR_ENV):
            assert is_flaresolverr_effective(FakeWatch({}),
                                             make_datastore(application_enabled=False)) is False


class TestCookieDomainValidation:
    def test_exact_match(self):
        assert is_cookie_domain_valid("example.com", "example.com") is True

    def test_subdomain_match_with_dot(self):
        assert is_cookie_domain_valid(".example.com", "www.example.com") is True

    def test_evil_domain_rejected(self):
        assert is_cookie_domain_valid("evil.com", "example.com") is False

    def test_suffix_without_dot_boundary_rejected(self):
        # "example.com" ends with "ample.com" but not ".ample.com"
        assert is_cookie_domain_valid("ample.com", "example.com") is False

    def test_port_suffixed_host_rejected(self):
        # Contract: callers pass urlparse().hostname (no port). A raw
        # netloc fails closed instead of matching the wrong domain.
        assert is_cookie_domain_valid("example.com", "example.com:8080") is False

    def test_empty_domain_scoped_via_url(self):
        assert is_cookie_domain_valid("", "example.com") is True

    def test_dot_only_rejected(self):
        assert is_cookie_domain_valid(".", "example.com") is False


class TestNormalizeFlareSolverrCookies:
    def test_none_and_empty(self):
        assert normalize_flaresolverr_cookies(None, WATCH_URL) == []
        assert normalize_flaresolverr_cookies([], WATCH_URL) == []

    def test_evil_domain_dropped(self):
        cookies = [{"name": "a", "value": "1", "domain": "evil.com"},
                   {"name": "cf_clearance", "value": "abc", "domain": "example.com"}]
        result = normalize_flaresolverr_cookies(cookies, WATCH_URL)
        assert [c["name"] for c in result] == ["cf_clearance"]

    def test_expires_coerced_to_float(self):
        result = normalize_flaresolverr_cookies([{"name": "a", "value": "1", "expires": 1700000000}],
                                                WATCH_URL)
        assert result[0]["expires"] == 1700000000.0
        assert isinstance(result[0]["expires"], float)

    def test_samesite_casefolded(self):
        result = normalize_flaresolverr_cookies([{"name": "a", "value": "1", "sameSite": "lax"}],
                                                WATCH_URL)
        assert result[0]["sameSite"] == "Lax"

    def test_samesite_all_valid_values(self):
        for raw, expected in [("strict", "Strict"), ("Strict", "Strict"), ("STRICT", "Strict"),
                              ("lax", "Lax"), ("Lax", "Lax"),
                              ("none", "None"), ("None", "None")]:
            result = normalize_flaresolverr_cookies([{"name": "a", "value": "1", "sameSite": raw}],
                                                    WATCH_URL)
            assert result[0]["sameSite"] == expected, raw

    def test_existing_url_preserved(self):
        result = normalize_flaresolverr_cookies(
            [{"name": "a", "value": "1", "url": "https://example.com/other"}], WATCH_URL)
        assert result[0]["url"] == "https://example.com/other"

    def test_none_url_with_cookies(self):
        result = normalize_flaresolverr_cookies([{"name": "a", "value": "1"}], None)
        assert result == [{"name": "a", "value": "1"}]

    def test_invalid_samesite_dropped_but_cookie_kept(self):
        result = normalize_flaresolverr_cookies([{"name": "a", "value": "1", "sameSite": "sometimes"}],
                                                WATCH_URL)
        assert result[0]["name"] == "a"
        assert "sameSite" not in result[0]

    def test_url_fallback_when_no_domain(self):
        result = normalize_flaresolverr_cookies([{"name": "a", "value": "1"}], WATCH_URL)
        assert result[0]["url"] == WATCH_URL

    def test_non_dict_entries_skipped(self):
        result = normalize_flaresolverr_cookies(["nope", {"name": "a", "value": "1"}], WATCH_URL)
        assert [c["name"] for c in result] == ["a"]

    def test_input_not_mutated(self):
        original = {"name": "a", "value": "1", "sameSite": "lax"}
        normalize_flaresolverr_cookies([original], WATCH_URL)
        assert original == {"name": "a", "value": "1", "sameSite": "lax"}


class FakePool:
    """Stands in for FlarePool; records solve() kwargs like the real signature."""

    def __init__(self, solution):
        self._solution = solution
        self.calls = []

    def solve(self, url, proxy_url=None, method="GET", post_data=None):
        self.calls.append({"url": url, "proxy_url": proxy_url, "method": method, "post_data": post_data})
        return self._solution


class TestFlarePoolSolve:
    def _pool(self, **kwargs):
        kwargs.setdefault("flaresolverr_url", "http://flaresolverr:8191/v1")
        kwargs.setdefault("timeout", 5)
        return FlarePool(**kwargs)

    def _posted(self, monkeypatch, solution):
        monkeypatch.setattr("changedetectionio.validate_url.is_fetch_url_allowed",
                            lambda url: (True, ""))
        posted = []
        timeouts = []

        def fake_post(url, json=None, timeout=None):
            posted.append((url, json))
            timeouts.append(timeout)
            return FakeResp({"status": "ok", "solution": solution})

        monkeypatch.setattr("requests.post", fake_post)
        return posted, timeouts

    def _ok(self, monkeypatch, solution):
        monkeypatch.setattr("changedetectionio.validate_url.is_fetch_url_allowed",
                            lambda url: (True, ""))
        posted = []

        def fake_post(url, json=None, timeout=None):
            posted.append(json)
            return FakeResp({"status": "ok", "solution": solution})

        monkeypatch.setattr("requests.post", fake_post)
        return posted

    def test_success_reuses_session(self, monkeypatch):
        posted = self._ok(monkeypatch, make_solution())
        pool = self._pool()
        first = pool.solve(WATCH_URL)
        second = pool.solve(WATCH_URL)
        assert first["session_id"] == second["session_id"]
        assert re.fullmatch(r"cdio-[0-9a-f]{12}", first["session_id"])
        assert not [p for p in posted if p.get("cmd") == "sessions.destroy"]

    def test_getter_defaults_and_invalid_fallback(self, monkeypatch):
        from changedetectionio.flaresolverr_pool import (
            get_flaresolverr_max_sessions,
            get_flaresolverr_timeout,
            get_flaresolverr_ttl_minutes,
        )
        with patch.dict("os.environ", {}, clear=True):
            assert get_flaresolverr_max_sessions() == 10
            assert get_flaresolverr_timeout() == 60
            assert get_flaresolverr_ttl_minutes() == 60
        with patch.dict("os.environ", {"FLARESOLVERR_MAX_SESSIONS": "abc",
                                       "FLARESOLVERR_TIMEOUT": "abc",
                                       "FLARESOLVERR_TTL_MINUTES": "abc"}):
            assert get_flaresolverr_max_sessions() == 10
            assert get_flaresolverr_timeout() == 60
            assert get_flaresolverr_ttl_minutes() == 60
        with patch.dict("os.environ", {"FLARESOLVERR_MAX_SESSIONS": "3",
                                       "FLARESOLVERR_TIMEOUT": "42",
                                       "FLARESOLVERR_TTL_MINUTES": "7"}):
            assert get_flaresolverr_max_sessions() == 3
            assert get_flaresolverr_timeout() == 42
            assert get_flaresolverr_ttl_minutes() == 7

    def test_lru_evict_destroys_old_session(self, monkeypatch):
        posted = self._ok(monkeypatch, make_solution())
        with patch.dict("os.environ", {"FLARESOLVERR_MAX_SESSIONS": "1"}):
            pool = self._pool()
            first = pool.solve("https://a.example.com/")
            pool.solve("https://b.example.com/")
        destroys = [p for p in posted if p.get("cmd") == "sessions.destroy"]
        assert [d["session"] for d in destroys] == [first["session_id"]]

    def test_expired_entry_evicted_on_resolve(self, monkeypatch):
        posted = self._ok(monkeypatch, make_solution())
        pool = self._pool()
        pool.solve(WATCH_URL)
        pool._lru["www.example.com"]["ts"] -= 61 * 60
        assert pool.get_cached(WATCH_URL) is None
        destroys = [p for p in posted if p.get("cmd") == "sessions.destroy"]
        assert len(destroys) == 1

    def test_expired_entry_evicted_on_solve(self, monkeypatch):
        posted = self._ok(monkeypatch, make_solution())
        pool = self._pool()
        first = pool.solve(WATCH_URL)
        # NOTE: no get_cached() in between — solve() itself must notice the
        # stale entry, destroy it and start fresh.
        pool._lru["www.example.com"]["ts"] -= 61 * 60
        second = pool.solve(WATCH_URL)
        destroys = [p for p in posted if p.get("cmd") == "sessions.destroy"]
        assert [d["session"] for d in destroys] == [first["session_id"]]
        assert second["session_id"] == first["session_id"]

    def test_entry_without_timestamp_is_expired(self, monkeypatch):
        posted = self._ok(monkeypatch, make_solution())
        pool = self._pool()
        pool.solve(WATCH_URL)
        del pool._lru["www.example.com"]["ts"]
        assert pool.get_cached(WATCH_URL) is None
        destroys = [p for p in posted if p.get("cmd") == "sessions.destroy"]
        assert len(destroys) == 1

    def test_max_zero_is_ephemeral(self, monkeypatch):
        posted = self._ok(monkeypatch, make_solution())
        with patch.dict("os.environ", {"FLARESOLVERR_MAX_SESSIONS": "0"}):
            pool = self._pool()
            solution = pool.solve(WATCH_URL)
        assert solution["session_id"] is None
        assert pool._lru == {}
        assert not [p for p in posted if p.get("cmd") == "sessions.destroy"]

    def test_ssrf_blocked_before_http(self, monkeypatch):
        monkeypatch.setattr("changedetectionio.validate_url.is_fetch_url_allowed",
                            lambda url: (False, "unit-test-block"))
        called = []
        monkeypatch.setattr("requests.post", lambda *a, **k: called.append((a, k)))
        pool = self._pool()
        with pytest.raises(FlareSolverrException, match="unit-test-block"):
            pool.solve("https://www.example.com/")
        assert called == []

    def test_real_gate_rejects_file_url(self, monkeypatch):
        called = []
        monkeypatch.setattr("requests.post", lambda *a, **k: called.append((a, k)))
        pool = self._pool()
        with pytest.raises(FlareSolverrException):
            pool.solve("file:///etc/passwd")
        assert called == []

    def test_full_request_payload(self, monkeypatch):
        posted, timeouts = self._posted(monkeypatch, make_solution())
        with patch.dict("os.environ", {"FLARESOLVERR_TTL_MINUTES": "7"}):
            pool = self._pool(timeout=42)
            solution = pool.solve(WATCH_URL, proxy_url="http://proxy:8080")
        assert len(posted) == 1
        url, payload = posted[0]
        assert url == "http://flaresolverr:8191/v1"
        assert payload == {"cmd": "request.get",
                           "url": WATCH_URL,
                           "maxTimeout": 42000,
                           "session": solution["session_id"],
                           "session_ttl_minutes": 7,
                           "proxy": {"url": "http://proxy:8080"}}
        assert timeouts == [47]

    def test_post_cmd_and_postdata(self, monkeypatch):
        posted, _ = self._posted(monkeypatch, make_solution())
        pool = self._pool()
        pool.solve(WATCH_URL, method="POST", post_data="a=1")
        _, payload = posted[0]
        assert payload["cmd"] == "request.post"
        assert payload["postData"] == "a=1"

    def test_exactly_1mb_post_data_not_truncated(self, monkeypatch):
        posted, _ = self._posted(monkeypatch, make_solution())
        pool = self._pool()
        body = "x" * (1024 * 1024)
        pool.solve(WATCH_URL, method="POST", post_data=body)
        assert len(posted[0][1]["postData"]) == 1024 * 1024

    def test_over_1mb_post_data_rejected(self, monkeypatch):
        posted, _ = self._posted(monkeypatch, make_solution())
        pool = self._pool()
        with pytest.raises(FlareSolverrException, match="too large"):
            pool.solve(WATCH_URL, method="POST", post_data="x" * (1024 * 1024 + 1))
        assert posted == []

    def test_max_zero_then_nonzero(self, monkeypatch):
        self._ok(monkeypatch, make_solution())
        with patch.dict("os.environ", {"FLARESOLVERR_MAX_SESSIONS": "0"}):
            pool = self._pool()
            assert pool.solve(WATCH_URL)["session_id"] is None
            assert pool._lru == {}
        with patch.dict("os.environ", {"FLARESOLVERR_MAX_SESSIONS": "10"}):
            solved = pool.solve(WATCH_URL)
            assert solved["session_id"].startswith("cdio-")
            assert pool.get_cached(WATCH_URL)["session_id"] == solved["session_id"]

    def test_error_message_defaults_to_empty(self, monkeypatch):
        monkeypatch.setattr("changedetectionio.validate_url.is_fetch_url_allowed",
                            lambda url: (True, ""))
        monkeypatch.setattr("requests.post",
                            lambda *a, **k: FakeResp({"status": "error"}))
        pool = self._pool()
        with pytest.raises(FlareSolverrException) as exc_info:
            pool.solve(WATCH_URL)
        assert str(exc_info.value) == "FlareSolverr error status=error msg="

    def test_get_cached_returns_live_entry(self, monkeypatch):
        self._ok(monkeypatch, make_solution())
        pool = self._pool()
        solved = pool.solve(WATCH_URL)
        cached = pool.get_cached(WATCH_URL)
        assert cached["session_id"] == solved["session_id"]
        assert cached["cookies"] == solved["cookies"]

    def test_destroy_posts_to_daemon_url(self, monkeypatch):
        posted, _ = self._posted(monkeypatch, make_solution())
        with patch.dict("os.environ", {"FLARESOLVERR_MAX_SESSIONS": "1"}):
            pool = self._pool()
            pool.solve("https://a.example.com/")
            pool.solve("https://b.example.com/")
        destroys = [(u, p) for u, p in posted if p.get("cmd") == "sessions.destroy"]
        assert len(destroys) == 1
        assert destroys[0][0] == "http://flaresolverr:8191/v1"

    def test_explicit_constructor_args_win_over_env(self, monkeypatch):
        self._ok(monkeypatch, make_solution())
        with patch.dict("os.environ", {"FLARESOLVERR_MAX_SESSIONS": "99",
                                       "FLARESOLVERR_TTL_MINUTES": "99",
                                       "FLARESOLVERR_TIMEOUT": "99"}):
            pool = FlarePool(flaresolverr_url="http://flaresolverr:8191/v1",
                             max_sessions=1, ttl_minutes=2, timeout=3)
            pool.solve("https://a.example.com/")
            pool.solve("https://b.example.com/")
            # MAX=1 from the constructor, not 99 from env: A must be evicted.
            assert "a.example.com" not in pool._lru
            assert pool.timeout == 3
            assert pool.ttl_minutes == 2

    def test_error_status_raises_and_evicts(self, monkeypatch):
        monkeypatch.setattr("changedetectionio.validate_url.is_fetch_url_allowed",
                            lambda url: (True, ""))
        posted = []

        def fake_post(url, json=None, timeout=None):
            posted.append(json)
            return FakeResp({"status": "error", "message": "boom"})

        monkeypatch.setattr("requests.post", fake_post)
        pool = self._pool()
        with pytest.raises(FlareSolverrException, match="boom"):
            pool.solve(WATCH_URL)
        destroys = [p for p in posted if p.get("cmd") == "sessions.destroy"]
        assert len(destroys) == 1
        assert destroys[0]["session"].startswith("cdio-")
        assert pool.get_cached(WATCH_URL) is None

    def test_empty_solution_raises(self, monkeypatch):
        monkeypatch.setattr("changedetectionio.validate_url.is_fetch_url_allowed",
                            lambda url: (True, ""))
        monkeypatch.setattr("requests.post",
                            lambda *a, **k: FakeResp({"status": "ok", "solution": {}}))
        pool = self._pool()
        with pytest.raises(FlareSolverrException, match="empty solution"):
            pool.solve(WATCH_URL)


class TestGetFlareSolverrSolutionForWatch:
    def _run(self, watch, datastore, proxy_url=None):
        with patch.dict("os.environ", FLARESOLVERR_ENV):
            return asyncio.run(get_flaresolverr_solution_for_watch(watch, datastore,
                                                                   proxy_url=proxy_url))

    def test_post_body_forwarded(self, monkeypatch):
        pool = FakePool(make_solution())
        monkeypatch.setattr("changedetectionio.flaresolverr_pool.get_global_pool", lambda: pool)
        watch = FakeWatch({"link": WATCH_URL, "method": "POST", "body": "a=1", "flaresolverr": "enabled"})
        solution = self._run(watch, make_datastore(application_enabled=True))
        assert solution["session_id"] == "cdio-test"
        assert pool.calls[0] == {"url": WATCH_URL, "proxy_url": None, "method": "POST", "post_data": "a=1"}

    def test_get_sends_no_post_data(self, monkeypatch):
        pool = FakePool(make_solution())
        monkeypatch.setattr("changedetectionio.flaresolverr_pool.get_global_pool", lambda: pool)
        watch = FakeWatch({"link": WATCH_URL, "method": "GET", "flaresolverr": "enabled"})
        self._run(watch, make_datastore(application_enabled=True))
        assert pool.calls[0]["method"] == "GET"
        assert pool.calls[0]["post_data"] is None

    def test_large_post_body_rejected(self, monkeypatch):
        pool = FakePool(make_solution())
        monkeypatch.setattr("changedetectionio.flaresolverr_pool.get_global_pool", lambda: pool)
        watch = FakeWatch({"link": WATCH_URL, "method": "POST",
                           "body": "x" * (2 * 1024 * 1024), "flaresolverr": "enabled"})
        with pytest.raises(FlareSolverrException, match="too large"):
            self._run(watch, make_datastore(application_enabled=True))
        assert pool.calls == []

    def test_not_effective_returns_none_without_pool(self, monkeypatch):
        pool = FakePool(make_solution())
        monkeypatch.setattr("changedetectionio.flaresolverr_pool.get_global_pool", lambda: pool)
        watch = FakeWatch({"link": WATCH_URL, "flaresolverr": "disabled"})
        with patch.dict("os.environ", FLARESOLVERR_ENV):
            assert asyncio.run(get_flaresolverr_solution_for_watch(
                watch, make_datastore(application_enabled=True))) is None
        assert pool.calls == []


class TestInjectCookies:
    def test_playwright_filters_evil_domain(self):
        context = SimpleNamespace(add_cookies=AsyncMock())
        cookies = [{"name": "evil", "value": "1", "domain": "evil.com"},
                   {"name": "cf_clearance", "value": "abc", "domain": "example.com", "expires": 1700000000}]
        count = asyncio.run(inject_cookies_playwright(context, cookies, "https://www.example.com/"))
        assert count == 1
        (payload,), _ = context.add_cookies.call_args
        assert [c["name"] for c in payload] == ["cf_clearance"]
        assert isinstance(payload[0]["expires"], float)

    def test_playwright_all_dropped_returns_zero(self):
        context = SimpleNamespace(add_cookies=AsyncMock())
        count = asyncio.run(inject_cookies_playwright(
            context, [{"name": "evil", "value": "1", "domain": "evil.com"}], WATCH_URL))
        assert count == 0
        context.add_cookies.assert_not_called()

    def test_puppeteer_set_cookie(self):
        page = SimpleNamespace(setCookie=AsyncMock())
        cookies = [{"name": "cf_clearance", "value": "abc", "domain": "example.com"}]
        count = asyncio.run(inject_cookies_puppeteer(page, cookies, WATCH_URL))
        assert count == 1
        page.setCookie.assert_called_once_with(*cookies)

    def test_selenium_strips_unsupported_keys(self):
        driver = MagicMock()
        cookies = [{"name": "c", "value": "v", "domain": ".example.com",
                    "expires": 1700000000, "sameSite": "lax", "url": WATCH_URL, "path": "/"}]
        count = inject_cookies_selenium(driver, cookies, WATCH_URL)
        assert count == 1
        driver.add_cookie.assert_called_once_with({"name": "c", "value": "v",
                                                   "domain": "example.com", "path": "/"})

    def test_selenium_all_dropped_returns_zero(self):
        driver = MagicMock()
        count = inject_cookies_selenium(driver, [{"name": "evil", "value": "1", "domain": "evil.com"}],
                                        WATCH_URL)
        assert count == 0
        driver.add_cookie.assert_not_called()


class TestUserAgent:
    def test_flaresolverr_ua_wins(self):
        assert resolve_flaresolverr_user_agent("FlareUA/1.0", headers={"User-Agent": "Other"}) == "FlareUA/1.0"

    def test_falls_back_to_manage_user_agent(self, monkeypatch):
        from unittest.mock import Mock
        manage = Mock(return_value="M-UA")
        monkeypatch.setattr("changedetectionio.content_fetchers.base.manage_user_agent", manage)
        assert resolve_flaresolverr_user_agent(None, headers={"X-A": "b"}) == "M-UA"
        manage.assert_called_once_with(headers={"X-A": "b"})

    def test_puppeteer_applies_flaresolverr_ua_and_strips_header(self):
        page = SimpleNamespace(setUserAgent=AsyncMock(), evaluate=AsyncMock(return_value="NAV-UA"))
        headers = {"User-Agent": "Old", "X-K": "v"}
        filtered = asyncio.run(apply_flaresolverr_user_agent_puppeteer(page, "FlareUA/1.0", headers))
        page.setUserAgent.assert_called_once_with("FlareUA/1.0")
        assert filtered == {"X-K": "v"}
        assert headers == {"User-Agent": "Old", "X-K": "v"}  # caller-owned dict untouched

    def test_puppeteer_uses_header_ua(self):
        page = SimpleNamespace(setUserAgent=AsyncMock(), evaluate=AsyncMock(return_value="NAV-UA"))
        filtered = asyncio.run(apply_flaresolverr_user_agent_puppeteer(
            page, None, {"user-agent": "  HeaderUA  ", "X-K": "v"}))
        page.setUserAgent.assert_called_once_with("HeaderUA")
        assert filtered == {"X-K": "v"}

    def test_puppeteer_falls_back_to_managed_ua(self, monkeypatch):
        from unittest.mock import Mock
        manage = Mock(return_value="M-UA")
        monkeypatch.setattr("changedetectionio.content_fetchers.base.manage_user_agent", manage)
        page = SimpleNamespace(setUserAgent=AsyncMock(), evaluate=AsyncMock(return_value="NAV-UA"))
        filtered = asyncio.run(apply_flaresolverr_user_agent_puppeteer(page, None, {"X-K": "v"}))
        page.setUserAgent.assert_called_once_with("M-UA")
        manage.assert_called_once_with(headers={"X-K": "v"}, current_ua="NAV-UA")
        assert filtered == {"X-K": "v"}


def make_handler_self(watch_extra=None, empty_pages_are_a_change=False):
    """Fake watch+datastore bundle: only what the overlay helpers touch."""
    watch = FakeWatch({"ignore_status_codes": False})
    if watch_extra:
        watch.update(watch_extra)
    datastore = SimpleNamespace(
        data={"settings": {"application": {"flaresolverr_enabled": True,
                                           "empty_pages_are_a_change": empty_pages_are_a_change},
                           "requests": {}}})
    return SimpleNamespace(watch=watch, datastore=datastore, fetcher=None,
                           screenshot_format="JPEG", worker_id="w1")


def make_fetcher_obj(made):
    def fake_fetcher_obj(**kwargs):
        fetcher = SimpleNamespace(quit=AsyncMock(), backend_name=None, kwargs=kwargs)
        made.append(fetcher)
        return fetcher
    return fake_fetcher_obj


class TestSolveFlareSolverr:
    def _run(self, watch, datastore, monkeypatch, result, proxy_url=None):
        monkeypatch.setattr("changedetectionio.flaresolverr_pool.get_flaresolverr_solution_for_watch",
                            AsyncMock(return_value=result))
        return asyncio.run(solve_flaresolverr(watch, datastore, WATCH_URL, proxy_url))

    def _handler(self):
        handler = make_handler_self()
        return handler.watch, handler.datastore

    def test_passthrough(self, monkeypatch):
        solution = make_solution()
        watch, datastore = self._handler()
        out = self._run(watch, datastore, monkeypatch, solution)
        assert out is solution

    def test_none_when_ineffective(self, monkeypatch):
        watch, datastore = self._handler()
        assert self._run(watch, datastore, monkeypatch, None) is None

    def test_error_mapped(self, monkeypatch):
        from unittest.mock import Mock
        monkeypatch.setattr("changedetectionio.flaresolverr_pool.get_flaresolverr_solution_for_watch",
                            Mock(side_effect=ValueError("down")))
        watch, datastore = self._handler()
        with pytest.raises(Exception, match="FlareSolverr: .*down"):
            asyncio.run(solve_flaresolverr(watch, datastore, WATCH_URL, None))

    def test_import_error_mapped(self, monkeypatch):
        # Regression: the import lives inside the try, so a REAL failed import
        # (not just a failing call) is wrapped as FlareSolverr:.
        monkeypatch.setitem(sys.modules, "changedetectionio.flaresolverr_pool", None)
        watch, datastore = self._handler()
        with pytest.raises(Exception, match="FlareSolverr:"):
            asyncio.run(solve_flaresolverr(watch, datastore, WATCH_URL, None))


class TestBareResponse:
    def _run(self, solution, watch_extra=None, empty_pages=False):
        handler = make_handler_self(watch_extra=watch_extra,
                                    empty_pages_are_a_change=empty_pages)
        made = []
        fetcher = asyncio.run(build_flaresolverr_bare_fetcher(
            solution, "html_requests", make_fetcher_obj(made),
            "http://proxy:8080", "ws://custom", handler.screenshot_format,
            handler.worker_id, handler.watch, handler.datastore, WATCH_URL))
        return fetcher, made, handler

    def test_happy_path(self):
        solution = make_solution(response="<html>ok</html>", status=200, headers={"ct": "t"})
        fetcher, made, handler = self._run(solution)
        assert len(made) == 1
        assert made[0].kwargs["worker_id"] == "w1"
        assert made[0].kwargs["proxy_override"] == "http://proxy:8080"
        assert made[0].kwargs["custom_browser_connection_url"] == "ws://custom"
        assert fetcher is made[0]
        assert fetcher.backend_name == "html_requests+flaresolverr"
        assert fetcher.content == "<html>ok</html>"
        assert fetcher.status_code == 200
        assert fetcher.headers == {"ct": "t"}
        fetcher.quit.assert_awaited_once_with(watch=handler.watch)

    def test_empty_response_raises(self):
        with pytest.raises(EmptyReply) as exc_info:
            self._run(make_solution(response="", status=200))
        assert exc_info.value.status_code == 200

    def test_empty_response_allowed_when_configured(self):
        fetcher, _, _ = self._run(make_solution(response="  ", status=200), empty_pages=True)
        assert fetcher.content == "  "

    def test_non200_raises(self):
        with pytest.raises(Non200ErrorCodeReceived) as exc_info:
            self._run(make_solution(response="<html>denied</html>", status=500))
        assert exc_info.value.status_code == 500

    def test_non200_ignored_when_configured(self):
        fetcher, _, _ = self._run(make_solution(response="<html>denied</html>", status=500),
                                  watch_extra={"ignore_status_codes": True})
        assert fetcher.status_code == 500

    def test_status_and_headers_default(self):
        fetcher, _, _ = self._run({"response": "<html>x</html>"})
        assert fetcher.status_code == 200
        assert fetcher.headers == {}

    def test_non_dict_headers_coerced(self):
        fetcher, _, _ = self._run({"response": "<html>x</html>", "headers": "notadict"})
        assert fetcher.headers == {}
