#!/usr/bin/env python3
"""Unit tests for the FlareSolverr overlay (changedetectionio/flaresolverr_pool.py).

No network, no daemon, no browser: the URL gate and requests.post are mocked,
browser APIs are faked with AsyncMock/MagicMock. Mirrors the pattern of
tests/unit/test_fetch_url_gate.py — pin the security-relevant behavior
(domain validation, SSRF gate, POST size guard) so a future refactor is the
only way to regress it.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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
    """Minimal watch stub: attribute access for .link, dict .get() for the rest."""

    @property
    def link(self):
        return self.get("link")


def make_datastore(application_enabled=None, requests_enabled=None):
    return SimpleNamespace(
        data={"settings": {"application": {"flaresolverr_enabled": application_enabled},
                           "requests": {"flaresolverr_enabled": requests_enabled}}}
    )


def make_solution(cookies=None, user_agent="FlareUA/1.0", response="<html>ok</html>", status=200):
    return {
        "cookies": cookies if cookies is not None else [{"name": "cf_clearance", "value": "abc",
                                                          "domain": "example.com", "path": "/"}],
        "userAgent": user_agent,
        "response": response,
        "url": WATCH_URL,
        "status": status,
        "headers": {},
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

    def test_port_stripped_before_compare(self):
        assert is_cookie_domain_valid("example.com", "example.com:8080") is True

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
        assert first["session_id"].startswith("cdio-")
        assert not [p for p in posted if p.get("cmd") == "sessions.destroy"]

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
        first = pool.solve(WATCH_URL)
        pool._lru["www.example.com"]["ts"] -= 61 * 60
        assert pool.get_cached(WATCH_URL) is None
        pool.solve(WATCH_URL)
        destroys = [p for p in posted if p.get("cmd") == "sessions.destroy"]
        assert [d["session"] for d in destroys] == [first["session_id"]]

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
        try:
            pool.solve("https://www.example.com/")
            assert False, "expected FlareSolverrException"
        except FlareSolverrException as e:
            assert "unit-test-block" in str(e)
        assert called == []

    def test_real_gate_rejects_file_url(self, monkeypatch):
        called = []
        monkeypatch.setattr("requests.post", lambda *a, **k: called.append((a, k)))
        pool = self._pool()
        try:
            pool.solve("file:///etc/passwd")
            assert False, "expected FlareSolverrException"
        except FlareSolverrException:
            pass
        assert called == []

    def test_error_status_raises_and_evicts(self, monkeypatch):
        monkeypatch.setattr("changedetectionio.validate_url.is_fetch_url_allowed",
                            lambda url: (True, ""))
        monkeypatch.setattr("requests.post",
                            lambda *a, **k: FakeResp({"status": "error", "message": "boom"}))
        pool = self._pool()
        try:
            pool.solve(WATCH_URL)
            assert False, "expected FlareSolverrException"
        except FlareSolverrException as e:
            assert "boom" in str(e)
        assert pool.get_cached(WATCH_URL) is None

    def test_empty_solution_raises(self, monkeypatch):
        monkeypatch.setattr("changedetectionio.validate_url.is_fetch_url_allowed",
                            lambda url: (True, ""))
        monkeypatch.setattr("requests.post",
                            lambda *a, **k: FakeResp({"status": "ok", "solution": {}}))
        pool = self._pool()
        try:
            pool.solve(WATCH_URL)
            assert False, "expected FlareSolverrException"
        except FlareSolverrException as e:
            assert "empty solution" in str(e)


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

    def test_large_post_body_truncated_to_1mb(self, monkeypatch):
        pool = FakePool(make_solution())
        monkeypatch.setattr("changedetectionio.flaresolverr_pool.get_global_pool", lambda: pool)
        watch = FakeWatch({"link": WATCH_URL, "method": "POST",
                           "body": "x" * (2 * 1024 * 1024), "flaresolverr": "enabled"})
        self._run(watch, make_datastore(application_enabled=True))
        assert len(pool.calls[0]["post_data"]) == 1024 * 1024

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
        monkeypatch.setattr("changedetectionio.content_fetchers.base.manage_user_agent",
                            lambda headers=None, current_ua="": "M-UA")
        assert resolve_flaresolverr_user_agent(None, headers={"X-A": "b"}) == "M-UA"

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
        monkeypatch.setattr("changedetectionio.content_fetchers.base.manage_user_agent",
                            lambda headers=None, current_ua="": "M-UA")
        page = SimpleNamespace(setUserAgent=AsyncMock(), evaluate=AsyncMock(return_value="NAV-UA"))
        filtered = asyncio.run(apply_flaresolverr_user_agent_puppeteer(page, None, {"X-K": "v"}))
        page.setUserAgent.assert_called_once_with("M-UA")
        assert filtered == {"X-K": "v"}
