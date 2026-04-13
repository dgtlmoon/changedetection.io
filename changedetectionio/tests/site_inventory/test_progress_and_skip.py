#!/usr/bin/env python3
"""Tests for:
  * on_progress callback (#9)
  * skip-if-unchanged config defaults and safety-valve (#8, processor-side;
    we cover the actual skip logic in the e2e test.)
"""
import pytest

from changedetectionio.processors.site_inventory_diff import crawler


def make_fake_get(pages):
    def _get(url, *, user_agent, timeout):
        if url in pages:
            return pages[url], "text/html", 200
        return None, "", 404
    return _get


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, dt):
        self.t += dt


class TestOnProgress:
    def test_callback_fires_every_n_fetches(self, monkeypatch):
        monkeypatch.setattr(
            "changedetectionio.processors.site_inventory_diff.crawler.is_private_hostname",
            lambda host: False,
        )

        # Build a seed whose page links to 10 children so we get plenty of
        # successful fetches.
        links = "".join(f'<a href="/p{i}">p{i}</a>' for i in range(10))
        pages = {"https://a.test/": links}
        for i in range(10):
            pages[f"https://a.test/p{i}"] = "<p>leaf</p>"

        calls: list[int] = []

        def on_progress(cr):
            calls.append(cr.pages_fetched)

        clk = FakeClock()
        res = crawler.crawl(
            seed_url="https://a.test/",
            max_pages=20,
            max_depth=2,
            crawl_delay_seconds=0,
            time_budget_seconds=100,
            respect_robots_txt=False,
            on_progress=on_progress,
            progress_every=3,
            _get=make_fake_get(pages),
            _now=clk,
            _sleep=clk.sleep,
        )
        # 11 successful fetches (seed + 10 pX). Callback should fire at
        # counts 3, 6, 9 — so exactly 3 times.
        assert res.pages_fetched == 11
        assert calls == [3, 6, 9], calls

    def test_no_callback_when_none(self, monkeypatch):
        monkeypatch.setattr(
            "changedetectionio.processors.site_inventory_diff.crawler.is_private_hostname",
            lambda host: False,
        )
        pages = {"https://a.test/": '<a href="/x">x</a>', "https://a.test/x": "x"}
        clk = FakeClock()
        # Passing on_progress=None must not raise.
        res = crawler.crawl(
            seed_url="https://a.test/",
            max_pages=5,
            max_depth=2,
            crawl_delay_seconds=0,
            time_budget_seconds=10,
            respect_robots_txt=False,
            on_progress=None,
            _get=make_fake_get(pages),
            _now=clk,
            _sleep=clk.sleep,
        )
        assert res.pages_fetched == 2

    def test_callback_exception_doesnt_abort_crawl(self, monkeypatch):
        monkeypatch.setattr(
            "changedetectionio.processors.site_inventory_diff.crawler.is_private_hostname",
            lambda host: False,
        )
        pages = {"https://a.test/": '<a href="/x">x</a>', "https://a.test/x": "x"}

        def boom(cr):
            raise RuntimeError("progress callback is buggy")

        clk = FakeClock()
        res = crawler.crawl(
            seed_url="https://a.test/",
            max_pages=5,
            max_depth=2,
            crawl_delay_seconds=0,
            time_budget_seconds=10,
            respect_robots_txt=False,
            on_progress=boom,
            progress_every=1,
            _get=make_fake_get(pages),
            _now=clk,
            _sleep=clk.sleep,
        )
        # Crawl completes normally despite the buggy callback.
        assert res.pages_fetched == 2


class TestConfigDefaults:
    def test_skip_defaults_present(self):
        from changedetectionio.processors.site_inventory_diff.processor import (
            _default_config,
        )
        cfg = _default_config()
        assert cfg["crawl_skip_if_seed_unchanged"] is True
        assert cfg["crawl_full_crawl_every_hours"] == 24
