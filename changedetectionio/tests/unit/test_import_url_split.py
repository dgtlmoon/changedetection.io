#!/usr/bin/env python3

"""Tests for the URL-list importer's url/tags splitting.

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_import_url_split

The importer accepts `<url> <tags>` per line, where tags are a comma separated list.
Splitting naively on the first space truncated any URL that legitimately contains
one - a query string with spaces (#1568) or a Jinja2 variable with spaces (#1516).

See #1568 and #1516.
"""

import unittest


class TestSplitUrlAndTags(unittest.TestCase):

    def _split(self, line):
        from changedetectionio.blueprint.imports.importer import split_url_and_tags
        return split_url_and_tags(line)

    # --- the documented format must keep working ---

    def test_plain_url_no_tags(self):
        self.assertEqual(self._split("https://example.com"), ("https://example.com", ""))

    def test_single_tag(self):
        self.assertEqual(self._split("https://example.com tag1"), ("https://example.com", "tag1"))

    def test_two_tags(self):
        self.assertEqual(self._split("https://example.com tag1, tag2"), ("https://example.com", "tag1, tag2"))

    def test_three_tags_last_one_has_a_space(self):
        self.assertEqual(
            self._split("https://example.com tag1, tag2, last tag"),
            ("https://example.com", "tag1, tag2, last tag")
        )

    def test_trailing_whitespace_is_stripped(self):
        self.assertEqual(self._split("  https://example.com tag1  "), ("https://example.com", "tag1"))

    def test_empty_line(self):
        self.assertEqual(self._split("   "), ("", ""))

    # --- #1568: a URL with spaces in the query string must not be truncated ---

    def test_url_with_spaces_in_query_string_is_kept_whole(self):
        line = "https://www.google.com/search?q=website monitoring and change detection"
        url, tags = self._split(line)

        self.assertEqual(tags, "", "the spaces belong to the URL, not to a tag list")
        self.assertIn("q=website", url)
        self.assertIn("monitoring", url)
        self.assertIn("change", url)

    def test_url_with_spaces_in_query_string_is_usable(self):
        from changedetectionio.validate_url import is_safe_valid_url

        line = "https://www.google.com/search?q=website monitoring and change detection"
        url, tags = self._split(line)

        self.assertEqual(tags, "")
        self.assertTrue(is_safe_valid_url(url), f"'{url}' should still be a valid watch URL")

    def test_url_with_spaces_in_query_string_is_not_truncated(self):
        """The whole point of #1568 - the tail of the URL must survive the import."""
        line = "https://www.google.com/search?q=website monitoring and change detection"
        url, tags = self._split(line)

        self.assertNotEqual(url, "https://www.google.com/search?q=website",
                            "the URL must not be truncated at the first space")
        self.assertEqual(url, line.strip())

    def test_url_with_spaces_in_query_string_is_escaped(self):
        line = "https://example.com/test?time=2025-10-28 09:19"
        url, tags = self._split(line)

        self.assertEqual(tags, "")
        self.assertIn("2025-10-28", url)
        self.assertIn("09:19", url)

    # --- #1516: a Jinja2 variable with spaces must not be truncated ---

    def test_jinja2_url_with_spaces_is_kept_whole(self):
        line = "https://changedetection.io/test.txt?date={% now 'Europe/Berlin', '%d' %}.{% now 'Europe/Berlin', '%m' %}"
        url, tags = self._split(line)

        self.assertEqual(tags, "", "the spaces belong to the Jinja2 expression, not to a tag list")
        self.assertTrue(url.startswith("https://changedetection.io/test.txt?date={%"),
                        f"the Jinja2 expression must survive intact, got '{url}'")
        self.assertIn("now 'Europe/Berlin'", url)

    def test_jinja2_url_keeps_the_full_expression(self):
        line = "https://changedetection.io/test.txt?date={% now 'Europe/Berlin', '%d' %}"
        url, tags = self._split(line)

        self.assertEqual(tags, "")
        self.assertEqual(url, line)

    # --- the tag list must survive the split ---

    def test_tags_are_returned_for_a_url_with_a_query_string(self):
        url, tags = self._split("https://example.com/page?a=1 tag1, tag2")

        self.assertEqual(url, "https://example.com/page?a=1")
        self.assertEqual(tags, "tag1, tag2")

    def test_no_tags_when_the_remainder_is_not_tag_like(self):
        # A single "tag" containing spaces is really part of the URL
        url, tags = self._split("https://example.com/some page here")

        self.assertEqual(tags, "")
        self.assertIn("some page here", url)


if __name__ == '__main__':
    unittest.main()
