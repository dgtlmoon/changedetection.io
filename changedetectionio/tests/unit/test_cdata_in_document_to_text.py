#!/usr/bin/env python3
"""cdata_in_document_to_text() runs on documents from the watched site, it must finish quickly on any input.

The regex it used before took exponentially longer on a CDATA section that was opened and never closed:
24 spaces after the opening took 4 seconds, 30 never finished.
"""
import time

from changedetectionio.html_tools import cdata_in_document_to_text


def test_cdata_content_becomes_text():
    feed = '<rss><title><![CDATA[ Hello <b>bold</b> &amp; more ]]></title><d><![CDATA[second]]></d></rss>'
    assert cdata_in_document_to_text(feed) == '<rss><title>Hello bold &amp; more</title><d>second</d></rss>'


def test_cdata_over_several_lines_and_empty():
    assert cdata_in_document_to_text('<a><![CDATA[\n line one\n line two\n]]></a>') == '<a>line one line two</a>'
    assert cdata_in_document_to_text('<a><![CDATA[]]></a>') == '<a></a>'


def test_document_without_cdata_is_unchanged():
    doc = '<rss><title>plain ]]> text</title></rss>'
    assert cdata_in_document_to_text(doc) == doc


def test_unclosed_cdata_is_left_alone_and_is_fast():
    doc = '<rss><a><![CDATA[closed]]></a><b><![CDATA[' + ' ' * 5000 + '</b></rss>'
    started = time.time()
    out = cdata_in_document_to_text(doc)
    assert time.time() - started < 2, "An unclosed CDATA section must not make this slow"
    assert out == '<rss><a>closed</a><b><![CDATA[' + ' ' * 5000 + '</b></rss>'


def test_many_unclosed_cdata_openings_are_fast():
    doc = '<![CDATA[ ' * 200000
    started = time.time()
    assert cdata_in_document_to_text(doc) == doc
    assert time.time() - started < 2
