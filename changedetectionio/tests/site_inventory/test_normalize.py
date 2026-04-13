#!/usr/bin/env python3
"""Unit tests for URL canonicalization — pure functions, no fixtures required."""

import pytest

from changedetectionio.processors.site_inventory_diff.normalize import (
    canonical_url,
    dedupe_and_sort,
    same_origin,
)


class TestCanonicalURL:
    def test_basic_absolute(self):
        assert canonical_url("https://Example.com/Foo") == "https://example.com/Foo"

    def test_drop_fragment(self):
        assert canonical_url("https://a.test/page#section-1") == "https://a.test/page"

    def test_strip_default_port(self):
        assert canonical_url("http://a.test:80/x") == "http://a.test/x"
        assert canonical_url("https://a.test:443/x") == "https://a.test/x"

    def test_keep_non_default_port(self):
        assert canonical_url("http://a.test:8080/x") == "http://a.test:8080/x"

    def test_collapse_double_slashes_in_path(self):
        assert canonical_url("https://a.test///a//b") == "https://a.test/a/b"

    def test_trailing_slash_stripped_on_deep_path(self):
        assert canonical_url("https://a.test/blog/") == "https://a.test/blog"

    def test_trailing_slash_kept_on_root(self):
        # Root path is kept as '/'
        assert canonical_url("https://a.test") == "https://a.test/"
        assert canonical_url("https://a.test/") == "https://a.test/"

    def test_strip_query_default(self):
        assert canonical_url("https://a.test/x?utm_source=foo&a=1") == "https://a.test/x"

    def test_keep_query_but_strip_tracking(self):
        got = canonical_url(
            "https://a.test/x?a=1&utm_source=foo&b=2",
            strip_query=False,
            strip_tracking_params_always=True,
        )
        # Sorted, tracking removed.
        assert got == "https://a.test/x?a=1&b=2"

    def test_keep_all_query_when_tracking_off(self):
        got = canonical_url(
            "https://a.test/x?utm_source=foo&a=1",
            strip_query=False,
            strip_tracking_params_always=False,
        )
        assert got == "https://a.test/x?a=1&utm_source=foo"

    def test_reject_non_http(self):
        assert canonical_url("mailto:hi@x.test") is None
        assert canonical_url("javascript:void(0)") is None
        assert canonical_url("tel:+1") is None

    def test_reject_empty(self):
        assert canonical_url("") is None
        assert canonical_url("   ") is None
        assert canonical_url(None) is None  # type: ignore[arg-type]

    def test_relative_resolved_against_base(self):
        got = canonical_url("/blog/hi", base_url="https://a.test/")
        assert got == "https://a.test/blog/hi"

    def test_invalid_is_safe(self):
        # Extremely malformed — should not raise.
        assert canonical_url("http://[::1::bad]/") is None or canonical_url("http://[::1::bad]/") is not None

    def test_idempotent(self):
        once = canonical_url("https://Example.com:443/Blog/?utm_source=x#frag")
        twice = canonical_url(once)
        assert once == twice == "https://example.com/Blog"


class TestSameOrigin:
    def test_exact_match(self):
        assert same_origin("https://a.test/x", "https://a.test/y")

    def test_www_vs_bare(self):
        # www prefix is stripped for comparison
        assert same_origin("https://a.test/x", "https://www.a.test/y")

    def test_different_host(self):
        assert not same_origin("https://a.test/x", "https://b.test/x")

    def test_scheme_ignored(self):
        assert same_origin("http://a.test/x", "https://a.test/y")


class TestDedupeSort:
    def test_unique_and_sorted(self):
        urls = ["https://b.test/1", "https://a.test/1", "https://b.test/1"]
        assert dedupe_and_sort(urls) == ["https://a.test/1", "https://b.test/1"]

    def test_drops_blanks(self):
        assert dedupe_and_sort(["", None, "https://a.test/"]) == ["https://a.test/"]
