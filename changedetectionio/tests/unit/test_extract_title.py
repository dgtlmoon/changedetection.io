#!/usr/bin/env python3
# coding=utf-8

"""Unit tests for html_tools.extract_title — including regression for #4217.

Issue #4217: extract_title silently returns None for pages where <title> is
pushed past the hard-coded 8 192-character scan window by large <head> content
(e.g. Amazon product pages where <title> can sit at character index 55 000+).
"""

import unittest

from changedetectionio.html_tools import extract_title


def _make_large_head_page(title: str, filler_count: int = 500) -> bytes:
    """Build a synthetic HTML page whose <title> is pushed far past 8 192 chars.

    Each filler line is ~126 bytes; 500 lines ≈ 63 000 bytes before <title>.
    """
    filler_line = '<meta name="x" content="' + "A" * 100 + '"/>\n'
    head_junk = filler_line * filler_count
    page = (
        f"<html><head>{head_junk}"
        f"<title>{title}</title>"
        f"</head><body></body></html>"
    )
    return page.encode("utf-8")


class TestExtractTitle(unittest.TestCase):
    # ------------------------------------------------------------------
    # Regression: issue #4217 — large <head> pushes <title> past scan limit
    # ------------------------------------------------------------------

    def test_large_head_bytes_title_extracted(self):
        """<title> beyond 8 192 bytes must still be extracted (bytes input)."""
        page = _make_large_head_page("Amazon Product Title - Real Title Here")
        title_pos = page.find(b"<title")
        self.assertGreater(
            title_pos,
            8192,
            f"Precondition: <title> must be past 8 192 chars (actual: {title_pos})",
        )
        result = extract_title(page)
        self.assertEqual(result, "Amazon Product Title - Real Title Here")

    def test_large_head_str_title_extracted(self):
        """<title> beyond 8 192 chars must still be extracted (str input)."""
        page_bytes = _make_large_head_page("Large Head String Test")
        page_str = page_bytes.decode("utf-8")
        title_pos = page_str.find("<title")
        self.assertGreater(title_pos, 8192)
        result = extract_title(page_str)
        self.assertEqual(result, "Large Head String Test")

    def test_very_large_head_55000_chars(self):
        """Simulate Amazon-like pages where <title> is at ~55 000 chars."""
        # Use a filler that puts the title at ~55 000 chars
        filler_line = '<meta name="description" content="' + "B" * 200 + '"/>\n'
        filler_count = 230  # ~235 bytes * 230 ≈ 54 050 chars before <title>
        head_junk = filler_line * filler_count
        page = (
            f"<html><head>{head_junk}"
            f"<title>ASIN B0B9CGQ14V - Echo Dot (5th Gen)</title>"
            f"</head><body>body content</body></html>"
        ).encode("utf-8")
        title_pos = page.find(b"<title")
        self.assertGreater(title_pos, 8192, f"<title> at {title_pos}, expected > 8192")
        result = extract_title(page)
        self.assertEqual(result, "ASIN B0B9CGQ14V - Echo Dot (5th Gen)")

    # ------------------------------------------------------------------
    # Baseline: small pages must continue to work
    # ------------------------------------------------------------------

    def test_normal_small_page(self):
        """Standard small page should extract title correctly."""
        page = b"<html><head><title>Simple Page</title></head><body>text</body></html>"
        self.assertEqual(extract_title(page), "Simple Page")

    def test_str_input_small_page(self):
        """str input small page."""
        page = "<html><head><title>String Input</title></head><body></body></html>"
        self.assertEqual(extract_title(page), "String Input")

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_no_title_tag_returns_none(self):
        """No <title> in document → None."""
        page = b"<html><head></head><body>no title here</body></html>"
        self.assertIsNone(extract_title(page))

    def test_empty_bytes_returns_none(self):
        """Empty bytes → None."""
        self.assertIsNone(extract_title(b""))

    def test_html_entities_decoded(self):
        """HTML entities inside <title> must be decoded."""
        page = b"<html><head><title>Caf&eacute; &amp; Tea</title></head><body></body></html>"
        self.assertEqual(extract_title(page), "Café & Tea")

    def test_extra_whitespace_collapsed(self):
        """Leading/trailing/internal whitespace in title is collapsed."""
        page = b"<html><head><title>  Multiple   Spaces  </title></head><body></body></html>"
        self.assertEqual(extract_title(page), "Multiple Spaces")

    def test_title_with_attributes_on_tag(self):
        """<title lang="en"> (tag with attributes) must still match."""
        page = b'<html><head><title lang="en">Attributed Title</title></head><body></body></html>'
        self.assertEqual(extract_title(page), "Attributed Title")

    def test_long_title_capped_at_2000_chars(self):
        """Titles longer than 2 000 chars are capped."""
        long_title = "T" * 3000
        page = f"<html><head><title>{long_title}</title></head><body></body></html>".encode()
        result = extract_title(page)
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 2000)

    def test_title_300_chars_preserved(self):
        """Titles up to 2 000 chars are preserved in full."""
        title = "X" * 300
        page = f"<html><head><title>{title}</title></head><body></body></html>".encode()
        self.assertEqual(extract_title(page), title)

    def test_unsupported_type_returns_none(self):
        """Passing an unsupported type (e.g. int) returns None without raising."""
        self.assertIsNone(extract_title(12345))  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
