#!/usr/bin/env python3
"""Unit tests for sitemap / sitemap-index / HTML anchor extraction."""

import gzip

import pytest

from changedetectionio.processors.site_inventory_diff import extractors


SITEMAP_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/a</loc></url>
  <url><loc>https://example.com/b</loc></url>
  <url><loc>https://example.com/c</loc></url>
</urlset>"""

SITEMAP_INDEX_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/sitemap-1.xml</loc></sitemap>
  <sitemap><loc>https://example.com/sitemap-2.xml</loc></sitemap>
</sitemapindex>"""

HTML_LISTING = """<html><body>
<nav><a href="/about">About</a></nav>
<div class="post-list">
  <a href="/blog/post-1">one</a>
  <a href="/blog/post-2">two</a>
  <a href="https://example.com/blog/post-3?utm_source=rss">three</a>
  <a href="mailto:hi@x.test">email</a>
  <a>no-href</a>
</div>
<footer><a href="/contact">Contact</a></footer>
</body></html>"""


class TestSniff:
    def test_sniff_by_content_type_xml(self):
        assert extractors.sniff_source_type(SITEMAP_XML, content_type="application/xml") == "sitemap"

    def test_sniff_index_over_urlset(self):
        assert extractors.sniff_source_type(SITEMAP_INDEX_XML, content_type="application/xml") == "sitemap_index"

    def test_sniff_html_default(self):
        assert extractors.sniff_source_type(b"<html></html>", content_type="text/html") == "html"

    def test_sniff_by_url_suffix(self):
        assert extractors.sniff_source_type(SITEMAP_XML, url="https://x.test/sitemap.xml") == "sitemap"


class TestSitemapExtraction:
    def test_basic_urlset(self):
        assert extractors.extract_from_sitemap_xml(SITEMAP_XML) == [
            "https://example.com/a",
            "https://example.com/b",
            "https://example.com/c",
        ]

    def test_gzipped_sitemap(self):
        compressed = gzip.compress(SITEMAP_XML)
        assert extractors.extract_from_sitemap_xml(compressed) == [
            "https://example.com/a",
            "https://example.com/b",
            "https://example.com/c",
        ]

    def test_malformed_returns_empty(self):
        assert extractors.extract_from_sitemap_xml(b"<<not-xml<<") == []

    def test_no_external_entities(self):
        # Billion-laughs / XXE payload; lxml parser is locked down.
        bad = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [
  <!ENTITY lol "lol">
  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;">
]>
<urlset><url><loc>&lol2;</loc></url></urlset>"""
        # Should not blow up; may return expanded or un-expanded text — what
        # matters is it doesn't amplify.
        out = extractors.extract_from_sitemap_xml(bad)
        assert isinstance(out, list)


class TestSitemapIndex:
    def test_index_flattens_children(self):
        def fake_fetch(child_url):
            # Both children return the same tiny sitemap for test simplicity.
            return SITEMAP_XML
        urls, capped = extractors.extract_from_sitemap_index(
            SITEMAP_INDEX_XML, fetch_child=fake_fetch
        )
        # Two children, each with 3 urls = 6 entries (pre-dedup).
        assert len(urls) == 6
        assert not capped

    def test_index_respects_child_cap(self):
        # Build a sitemap index with 10 children, cap at 3.
        children = "".join(
            f"<sitemap><loc>https://example.com/sm-{i}.xml</loc></sitemap>"
            for i in range(10)
        )
        payload = (
            "<?xml version=\"1.0\"?>"
            f"<sitemapindex xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">"
            f"{children}"
            "</sitemapindex>"
        ).encode("utf-8")

        calls = []

        def fake_fetch(child_url):
            calls.append(child_url)
            return SITEMAP_XML

        urls, capped = extractors.extract_from_sitemap_index(
            payload, fetch_child=fake_fetch, child_cap=3
        )
        assert capped
        assert len(calls) == 3  # only first three were fetched
        assert len(urls) == 9  # 3 children × 3 urls each

    def test_index_tolerates_failed_children(self):
        def fake_fetch(child_url):
            if "sitemap-1" in child_url:
                return None  # simulate HTTP failure
            return SITEMAP_XML
        urls, _ = extractors.extract_from_sitemap_index(
            SITEMAP_INDEX_XML, fetch_child=fake_fetch
        )
        assert len(urls) == 3  # only one child succeeded


class TestHTMLExtraction:
    def test_basic_anchor_extraction(self):
        urls = extractors.extract_from_html(HTML_LISTING, base_url="https://example.com/blog/")
        # Relative hrefs resolved; mailto / empty-href skipped.
        assert "https://example.com/about" in urls
        assert "https://example.com/blog/post-1" in urls
        assert "https://example.com/blog/post-3?utm_source=rss" in urls
        assert "https://example.com/contact" in urls
        assert not any("mailto:" in u for u in urls)

    def test_css_scope_restricts(self):
        urls = extractors.extract_from_html(
            HTML_LISTING,
            base_url="https://example.com/blog/",
            css_scope=".post-list",
        )
        # Only anchors inside .post-list — about/contact are outside.
        assert "https://example.com/blog/post-1" in urls
        assert "https://example.com/blog/post-2" in urls
        assert "https://example.com/about" not in urls
        assert "https://example.com/contact" not in urls

    def test_css_scope_missing_returns_empty(self):
        urls = extractors.extract_from_html(
            HTML_LISTING,
            base_url="https://example.com/",
            css_scope=".this-does-not-exist",
        )
        assert urls == []

    def test_bad_html_returns_list(self):
        assert extractors.extract_from_html("", base_url="https://a.test/") == []
