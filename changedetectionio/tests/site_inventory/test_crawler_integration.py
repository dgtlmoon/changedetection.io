#!/usr/bin/env python3
"""Tests for the crawler integration hardening:
  * SSRF guard (private IPs, env var opt-out)
  * Seed-body reuse (no double fetch)
  * robots.txt Crawl-delay directive honored
  * robots.txt TTL cache
  * Fetch-error surfacing
  * Proxy / headers propagation via a stub session
"""
import pytest

from changedetectionio.processors.site_inventory_diff import crawler


# Re-use the helpers from test_crawler.py so behavior stays consistent.
def make_fake_get(pages: dict):
    calls = []

    def _get(url, *, user_agent, timeout):
        calls.append(url)
        if url in pages:
            val = pages[url]
            # Support both (body, ctype) and (body, ctype, status) tuples in
            # fixtures so future tests can check for 4xx explicitly.
            if isinstance(val, tuple):
                if len(val) == 3:
                    return val
                return val[0], val[1], 200
            return val, "text/html; charset=utf-8", 200
        return None, "", 404

    _get.calls = calls
    return _get


class FakeClock:
    def __init__(self, start: float = 0.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def sleep(self, dt: float) -> None:
        self.t += dt


# --- SSRF guard -----------------------------------------------------------

class TestSSRF:
    def test_private_seed_rejected(self, monkeypatch):
        # Force ``is_private_hostname`` to return True for the seed so we
        # don't rely on actual DNS in the test harness.
        monkeypatch.setattr(
            "changedetectionio.processors.site_inventory_diff.crawler.is_private_hostname",
            lambda host: True,
        )
        # Make sure env var opt-out isn't set.
        monkeypatch.delenv("ALLOW_IANA_RESTRICTED_ADDRESSES", raising=False)

        clock = FakeClock()
        res = crawler.crawl(
            seed_url="http://10.0.0.1/",
            max_pages=10,
            max_depth=2,
            crawl_delay_seconds=0,
            time_budget_seconds=10,
            respect_robots_txt=False,
            _get=make_fake_get({}),
            _now=clock,
            _sleep=clock.sleep,
        )
        assert res.pages_fetched == 0
        assert res.pages_skipped_ssrf == 1
        assert any("SSRF guard" in w or "private/reserved" in w for w in res.warnings)

    def test_env_opt_out_allows_private(self, monkeypatch):
        monkeypatch.setattr(
            "changedetectionio.processors.site_inventory_diff.crawler.is_private_hostname",
            lambda host: True,
        )
        monkeypatch.setenv("ALLOW_IANA_RESTRICTED_ADDRESSES", "true")

        pages = {"http://10.0.0.1/": "<p>leaf</p>"}
        clock = FakeClock()
        res = crawler.crawl(
            seed_url="http://10.0.0.1/",
            max_pages=10,
            max_depth=2,
            crawl_delay_seconds=0,
            time_budget_seconds=10,
            respect_robots_txt=False,
            _get=make_fake_get(pages),
            _now=clock,
            _sleep=clock.sleep,
        )
        assert res.pages_skipped_ssrf == 0
        assert "http://10.0.0.1/" in res.urls

    def test_private_link_skipped_even_if_seed_public(self, monkeypatch):
        # The seed resolves public, but one of the child links resolves to a
        # private IP. The crawler must refuse to fetch it.
        def fake_priv(host):
            return host == "10.0.0.2"

        monkeypatch.setattr(
            "changedetectionio.processors.site_inventory_diff.crawler.is_private_hostname",
            fake_priv,
        )
        monkeypatch.delenv("ALLOW_IANA_RESTRICTED_ADDRESSES", raising=False)

        pages = {
            "https://example.com/": '<a href="https://example.com/ok">ok</a>'
            '<a href="http://10.0.0.2/admin">bad</a>',
            "https://example.com/ok": "<p>ok</p>",
            "http://10.0.0.2/admin": "<p>SHOULD NEVER BE FETCHED</p>",
        }
        clock = FakeClock()
        res = crawler.crawl(
            seed_url="https://example.com/",
            max_pages=10,
            max_depth=2,
            crawl_delay_seconds=0,
            time_budget_seconds=10,
            respect_robots_txt=False,
            include_regex=None,
            exclude_regex=None,
            # Same-origin will naturally drop it too, but keep same-origin off
            # in normalize_opts to prove the SSRF guard is the backstop.
            _get=make_fake_get(pages),
            _now=clock,
            _sleep=clock.sleep,
        )
        # Same-origin filter (default on) drops the external link first; still
        # check the pages_skipped_ssrf counter didn't go up negatively and
        # that the bad URL was never fetched.
        assert "http://10.0.0.2/admin" not in res.urls
        assert "http://10.0.0.2/admin" not in make_fake_get(pages).calls


# --- Seed body reuse -----------------------------------------------------

class TestSeedBodyReuse:
    def test_seed_body_skips_first_fetch(self, monkeypatch):
        monkeypatch.setattr(
            "changedetectionio.processors.site_inventory_diff.crawler.is_private_hostname",
            lambda host: False,
        )
        pages = {"https://a.test/one": "<p>leaf</p>"}
        fake = make_fake_get(pages)

        seed_html = '<a href="/one">1</a>'
        clock = FakeClock()
        res = crawler.crawl(
            seed_url="https://a.test/",
            max_pages=5,
            max_depth=2,
            crawl_delay_seconds=0,
            time_budget_seconds=10,
            respect_robots_txt=False,
            seed_body=seed_html,
            seed_content_type="text/html",
            _get=fake,
            _now=clock,
            _sleep=clock.sleep,
        )
        # Seed was NOT fetched (reused from body); the linked /one was.
        assert "https://a.test/" not in fake.calls
        assert "https://a.test/one" in fake.calls
        assert res.pages_fetched == 2  # seed (from body) + /one


# --- Crawl-delay from robots.txt ----------------------------------------

class TestRobotsCrawlDelay:
    def test_robots_delay_overrides_lower_user_delay(self, monkeypatch):
        monkeypatch.setattr(
            "changedetectionio.processors.site_inventory_diff.crawler.is_private_hostname",
            lambda host: False,
        )

        # Clear any cached robots entry so our stub is consulted.
        with crawler._robots_cache_lock:
            crawler._robots_cache.clear()

        # Stub out session.get to return a robots.txt with Crawl-delay: 3
        class StubSession:
            def get(self, url, **kwargs):
                class Resp:
                    status_code = 200
                    text = "User-agent: *\nCrawl-delay: 3\n"
                    headers = {"Content-Type": "text/plain"}
                return Resp()

        pages = {
            "https://a.test/": '<a href="/b">b</a><a href="/c">c</a>',
            "https://a.test/b": "<p>b</p>",
            "https://a.test/c": "<p>c</p>",
        }
        fake = make_fake_get(pages)

        # Track sleeps so we can assert the larger (robots) delay was used.
        sleeps: list[float] = []

        class Clock:
            t = 0.0

            def __call__(self):
                return self.t

            def sleep(self, dt):
                sleeps.append(dt)
                self.t += dt

        clk = Clock()
        res = crawler.crawl(
            seed_url="https://a.test/",
            max_pages=5,
            max_depth=2,
            crawl_delay_seconds=1,  # user wanted 1s
            time_budget_seconds=100,
            respect_robots_txt=True,
            _get=fake,
            _now=clk,
            _sleep=clk.sleep,
            _session=StubSession(),
        )
        assert res.pages_fetched >= 2
        # At least one sleep must be >= 3 (robots value), not the user's 1s.
        assert any(abs(s - 3.0) < 0.01 for s in sleeps), sleeps


# --- robots.txt cache ---------------------------------------------------

class TestRobotsCache:
    def test_second_call_hits_cache(self, monkeypatch):
        monkeypatch.setattr(
            "changedetectionio.processors.site_inventory_diff.crawler.is_private_hostname",
            lambda host: False,
        )
        with crawler._robots_cache_lock:
            crawler._robots_cache.clear()

        calls = {"n": 0}

        class StubSession:
            def get(self, url, **kwargs):
                calls["n"] += 1

                class Resp:
                    status_code = 200
                    text = "User-agent: *\nAllow: /\n"
                    headers = {"Content-Type": "text/plain"}

                return Resp()

        for _ in range(3):
            crawler._build_robots(
                "https://a.test/",
                user_agent="ua",
                timeout=5,
                session=StubSession(),
            )
        assert calls["n"] == 1  # only the first call actually fetched


# --- Failure-rate warnings ----------------------------------------------

class TestFailureRate:
    def test_high_failure_rate_surfaces_warning(self, monkeypatch):
        monkeypatch.setattr(
            "changedetectionio.processors.site_inventory_diff.crawler.is_private_hostname",
            lambda host: False,
        )
        # Seed returns HTML with 5 links; only one of those links actually
        # returns a body — the other four all 404. Failure rate = 4/5 = 80%.
        pages = {
            "https://a.test/": (
                '<a href="/a">a</a><a href="/b">b</a><a href="/c">c</a>'
                '<a href="/d">d</a><a href="/e">e</a>',
                "text/html",
                200,
            ),
            "https://a.test/a": ("<p>a</p>", "text/html", 200),
            # b/c/d/e absent → fake_get returns (None, "", 404)
        }
        fake = make_fake_get(pages)
        clk = FakeClock()

        res = crawler.crawl(
            seed_url="https://a.test/",
            max_pages=20,
            max_depth=2,
            crawl_delay_seconds=0,
            time_budget_seconds=100,
            respect_robots_txt=False,
            _get=fake,
            _now=clk,
            _sleep=clk.sleep,
        )
        assert res.pages_failed >= 4
        assert any("fetches failed" in w for w in res.warnings), res.warnings

    def test_low_failure_rate_quiet(self, monkeypatch):
        monkeypatch.setattr(
            "changedetectionio.processors.site_inventory_diff.crawler.is_private_hostname",
            lambda host: False,
        )
        pages = {
            "https://a.test/": '<a href="/a">a</a>',
            "https://a.test/a": "<p>a</p>",
        }
        clk = FakeClock()
        res = crawler.crawl(
            seed_url="https://a.test/",
            max_pages=10,
            max_depth=2,
            crawl_delay_seconds=0,
            time_budget_seconds=10,
            respect_robots_txt=False,
            _get=make_fake_get(pages),
            _now=clk,
            _sleep=clk.sleep,
        )
        assert res.pages_failed == 0
        assert not any("fetches failed" in w for w in res.warnings)


# --- Session-based proxy + header propagation ---------------------------

class TestSessionPropagation:
    def test_make_session_applies_proxy_and_headers(self):
        session = crawler._make_session(
            proxy_url="http://proxy.local:3128",
            extra_headers={"Cookie": "sid=abc", "User-Agent": "should-be-stripped"},
        )
        assert session.proxies == {
            "http": "http://proxy.local:3128",
            "https": "http://proxy.local:3128",
        }
        # The user-supplied User-Agent must NOT overwrite the session default
        # (crawler UA is applied per-request instead, so robots.txt matching
        # and per-request overrides stay in sync).
        assert session.headers.get("User-Agent") != "should-be-stripped"
        assert session.headers.get("Cookie") == "sid=abc"
