#!/usr/bin/env python3
"""
Unit tests for XPath default namespace handling in RSS/Atom feeds.
Tests the fix for issue where //title/text() returns empty on feeds with default namespaces.

Real-world test data from https://github.com/microsoft/PowerToys/releases.atom
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import html_tools


# Real-world Atom feed with default namespace from GitHub PowerToys releases
# This is the actual format that was failing before the fix
atom_feed_with_default_ns = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/" xml:lang="en-US">
  <id>tag:github.com,2008:https://github.com/microsoft/PowerToys/releases</id>
  <link type="text/html" rel="alternate" href="https://github.com/microsoft/PowerToys/releases"/>
  <link type="application/atom+xml" rel="self" href="https://github.com/microsoft/PowerToys/releases.atom"/>
  <title>Release notes from PowerToys</title>
  <updated>2025-10-23T08:53:12Z</updated>
  <entry>
    <id>tag:github.com,2008:Repository/184456251/v0.95.1</id>
    <updated>2025-10-24T14:20:14Z</updated>
    <link rel="alternate" type="text/html" href="https://github.com/microsoft/PowerToys/releases/tag/v0.95.1"/>
    <title>Release 0.95.1</title>
    <content type="html">&lt;p&gt;This patch release fixes several important stability issues.&lt;/p&gt;</content>
    <author>
      <name>Jaylyn-Barbee</name>
    </author>
  </entry>
  <entry>
    <id>tag:github.com,2008:Repository/184456251/v0.95.0</id>
    <updated>2025-10-17T12:51:21Z</updated>
    <link rel="alternate" type="text/html" href="https://github.com/microsoft/PowerToys/releases/tag/v0.95.0"/>
    <title>Release v0.95.0</title>
    <content type="html">&lt;p&gt;New features, stability, optimization improvements.&lt;/p&gt;</content>
    <author>
      <name>Jaylyn-Barbee</name>
    </author>
  </entry>
</feed>"""

# RSS feed without default namespace
rss_feed_no_default_ns = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Channel Title</title>
    <description>Channel Description</description>
    <item>
      <title>Item 1 Title</title>
      <description>Item 1 Description</description>
    </item>
    <item>
      <title>Item 2 Title</title>
      <description>Item 2 Description</description>
    </item>
  </channel>
</rss>"""

# RSS 2.0 feed with namespace prefix (not default)
rss_feed_with_ns_prefix = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:dc="http://purl.org/dc/elements/1.1/"
     xmlns:content="http://purl.org/rss/1.0/modules/content/"
     xmlns:atom="http://www.w3.org/2005/Atom"
     version="2.0">
  <channel>
    <title>Channel Title</title>
    <atom:link href="http://example.com/feed" rel="self" type="application/rss+xml"/>
    <item>
      <title>Item Title</title>
      <dc:creator>Author Name</dc:creator>
    </item>
  </channel>
</rss>"""


class TestXPathDefaultNamespace:
    """Test XPath queries on feeds with and without default namespaces."""

    def test_atom_feed_simple_xpath_with_xpath_filter(self):
        """Test that //title/text() works on Atom feed with default namespace using xpath_filter."""
        result = html_tools.xpath_filter('//title/text()', atom_feed_with_default_ns, is_xml=True)
        assert 'Release notes from PowerToys' in result
        assert 'Release 0.95.1' in result
        assert 'Release v0.95.0' in result

    def test_atom_feed_nested_xpath_with_xpath_filter(self):
        """Test nested XPath like //entry/title/text() on Atom feed."""
        result = html_tools.xpath_filter('//entry/title/text()', atom_feed_with_default_ns, is_xml=True)
        assert 'Release 0.95.1' in result
        assert 'Release v0.95.0' in result
        # Should NOT include the feed title
        assert 'Release notes from PowerToys' not in result

    def test_atom_feed_other_elements_with_xpath_filter(self):
        """Test that other elements like //updated/text() work on Atom feed."""
        result = html_tools.xpath_filter('//updated/text()', atom_feed_with_default_ns, is_xml=True)
        assert '2025-10-23T08:53:12Z' in result
        assert '2025-10-24T14:20:14Z' in result

    def test_rss_feed_without_namespace(self):
        """Test that //title/text() works on RSS feed without default namespace."""
        result = html_tools.xpath_filter('//title/text()', rss_feed_no_default_ns, is_xml=True)
        assert 'Channel Title' in result
        assert 'Item 1 Title' in result
        assert 'Item 2 Title' in result

    def test_rss_feed_nested_xpath(self):
        """Test nested XPath on RSS feed without default namespace."""
        result = html_tools.xpath_filter('//item/title/text()', rss_feed_no_default_ns, is_xml=True)
        assert 'Item 1 Title' in result
        assert 'Item 2 Title' in result
        # Should NOT include channel title
        assert 'Channel Title' not in result

    def test_rss_feed_with_prefixed_namespaces(self):
        """Test that feeds with namespace prefixes (not default) still work."""
        result = html_tools.xpath_filter('//title/text()', rss_feed_with_ns_prefix, is_xml=True)
        assert 'Channel Title' in result
        assert 'Item Title' in result

    def test_local_name_workaround_still_works(self):
        """Test that local-name() workaround still works for Atom feeds."""
        result = html_tools.xpath_filter('//*[local-name()="title"]/text()', atom_feed_with_default_ns, is_xml=True)
        assert 'Release notes from PowerToys' in result
        assert 'Release 0.95.1' in result

    def test_xpath1_filter_without_default_namespace(self):
        """Test xpath1_filter works on RSS without default namespace."""
        result = html_tools.xpath1_filter('//title/text()', rss_feed_no_default_ns, is_xml=True)
        assert 'Channel Title' in result
        assert 'Item 1 Title' in result

    def test_xpath1_filter_with_default_namespace_returns_empty(self):
        """Test that xpath1_filter returns empty on Atom with default namespace (known limitation)."""
        result = html_tools.xpath1_filter('//title/text()', atom_feed_with_default_ns, is_xml=True)
        # xpath1_filter (lxml) doesn't support default namespaces, so this returns empty
        assert result == ''

    def test_xpath1_filter_local_name_workaround(self):
        """Test that xpath1_filter works with local-name() workaround on Atom feeds."""
        result = html_tools.xpath1_filter('//*[local-name()="title"]/text()', atom_feed_with_default_ns, is_xml=True)
        assert 'Release notes from PowerToys' in result
        assert 'Release 0.95.1' in result


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
