#!/usr/bin/env python3
"""Unit tests for the bounded crawler.

Uses a fake HTTP client and a fake clock so the tests are deterministic and
don't hit the network.
"""

import pytest

from changedetectionio.processors.site_inventory_diff import crawler


# ---- Test doubles --------------------------------------------------------

def make_fake_get(pages: dict[str, str]):
    """Return an HTTP-get-style callable backed by an in-memory dict."""
    calls = []

    def _get(url, *, user_agent, timeout):  # signature matches crawler._default_get
        calls.append(url)
        if url in pages:
            return pages[url], "text/html; charset=utf-8"
        return None, ""

    _get.calls = calls  # type: ignore[attr-defined]
    return _get


class FakeClock:
    def __init__(self, start: float = 0.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def sleep(self, dt: float) -> None:
        # Tiny virtual sleep — advance the clock but never block a real OS thread.
        self.t += dt


# ---- Tests ---------------------------------------------------------------

class TestCrawl:
    def test_same_origin_only(self):
        pages = {
            "https://a.test/": '<a href="/b">b</a><a href="https://other.test/x">x</a>',
            "https://a.test/b": '<a href="/c">c</a>',
            "https://a.test/c": "<p>leaf</p>",
        }
        clock = FakeClock()
        res = crawler.crawl(
            seed_url="https://a.test/",
            max_pages=10,
            max_depth=3,
            crawl_delay_seconds=0,
            time_budget_seconds=10,
            respect_robots_txt=False,
            _get=make_fake_get(pages),
            _now=clock,
            _sleep=clock.sleep,
        )
        assert "https://a.test/" in res.urls
        assert "https://a.test/b" in res.urls
        assert "https://a.test/c" in res.urls
        assert not any("other.test" in u for u in res.urls)

    def test_max_pages_cap(self):
        pages = {
            "https://a.test/": '<a href="/1">1</a><a href="/2">2</a><a href="/3">3</a>',
            "https://a.test/1": "<p>1</p>",
            "https://a.test/2": "<p>2</p>",
            "https://a.test/3": "<p>3</p>",
        }
        clock = FakeClock()
        res = crawler.crawl(
            seed_url="https://a.test/",
            max_pages=2,
            max_depth=3,
            crawl_delay_seconds=0,
            time_budget_seconds=10,
            respect_robots_txt=False,
            _get=make_fake_get(pages),
            _now=clock,
            _sleep=clock.sleep,
        )
        assert res.hit_max_pages
        assert res.pages_fetched == 2

    def test_max_depth_stops_expansion(self):
        pages = {
            "https://a.test/": '<a href="/d1">d1</a>',
            "https://a.test/d1": '<a href="/d2">d2</a>',
            "https://a.test/d2": '<a href="/d3">d3</a>',
        }
        clock = FakeClock()
        res = crawler.crawl(
            seed_url="https://a.test/",
            max_pages=50,
            max_depth=1,
            crawl_delay_seconds=0,
            time_budget_seconds=10,
            respect_robots_txt=False,
            _get=make_fake_get(pages),
            _now=clock,
            _sleep=clock.sleep,
        )
        # seed (depth 0) + one hop (depth 1). /d2 linked at depth 1 gets fetched?
        # No — crawler only expands when depth < max_depth. At depth 1 we stop expanding.
        assert "https://a.test/" in res.urls
        assert "https://a.test/d1" in res.urls
        assert "https://a.test/d2" not in res.urls
        assert res.hit_max_depth

    def test_time_budget(self):
        pages = {
            "https://a.test/": '<a href="/a">a</a>',
            "https://a.test/a": '<a href="/b">b</a>',
            "https://a.test/b": "<p>ok</p>",
        }
        clock = FakeClock()

        # Custom sleep jumps the clock by 5s per call, exhausting the budget fast.
        def big_sleep(dt):
            clock.t += 100

        res = crawler.crawl(
            seed_url="https://a.test/",
            max_pages=50,
            max_depth=5,
            crawl_delay_seconds=1,  # triggers our big_sleep
            time_budget_seconds=1,
            respect_robots_txt=False,
            _get=make_fake_get(pages),
            _now=clock,
            _sleep=big_sleep,
        )
        assert res.hit_time_budget

    def test_include_exclude_regex(self):
        pages = {
            "https://a.test/": '<a href="/blog/1">b1</a><a href="/tag/x">t</a>',
            "https://a.test/blog/1": "<p>leaf</p>",
            "https://a.test/tag/x": "<p>tag</p>",
        }
        clock = FakeClock()
        res = crawler.crawl(
            seed_url="https://a.test/",
            max_pages=10,
            max_depth=2,
            crawl_delay_seconds=0,
            time_budget_seconds=10,
            respect_robots_txt=False,
            include_regex=r"/blog/",
            exclude_regex=r"/tag/",
            _get=make_fake_get(pages),
            _now=clock,
            _sleep=clock.sleep,
        )
        assert "https://a.test/blog/1" in res.urls
        assert not any("/tag/" in u for u in res.urls)

    def test_invalid_seed(self):
        res = crawler.crawl(
            seed_url="not a url",
            max_pages=5,
            max_depth=1,
            crawl_delay_seconds=0,
            time_budget_seconds=10,
            respect_robots_txt=False,
            _get=make_fake_get({}),
            _now=FakeClock(),
            _sleep=lambda dt: None,
        )
        assert res.urls == set()
        assert res.warnings  # something was reported
