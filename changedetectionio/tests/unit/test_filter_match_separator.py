#!/usr/bin/env python3
import unittest

from changedetectionio import html_tools

# A page whose <link> elements give five distinct href attribute values, so a multi-match
# filter has something to separate. Paraphrased from #4477.
LINK_PAGE = """<html><head>
<link rel="apple-touch-icon" href="/static/apple-touch/wikipedia.png">
<link rel="icon" href="/static/favicon/wikipedia.ico">
<link rel="license" href="//creativecommons.org/licenses/by-sa/4.0/">
<link rel="stylesheet" href="//upload.wikimedia.org/style.css">
<link rel="alternate" href="https://wikis.world/@wikipedia">
</head><body>Page body</body></html>"""

HREFS = ['/static/apple-touch/wikipedia.png',
         '/static/favicon/wikipedia.ico',
         '//creativecommons.org/licenses/by-sa/4.0/',
         '//upload.wikimedia.org/style.css',
         'https://wikis.world/@wikipedia']


class TestSourceTypeFilterSeparator(unittest.TestCase):
    """#4477: a `source:` watch runs an XPath/CSS filter over more than one match.

    processor.py passes append_pretty_line_formatting=not self.watch.is_source_type_url, and
    for a `source:` watch the filtered text is then kept verbatim instead of going through
    html_to_text(). So TEXT_FILTER_LIST_LINE_SUFFIX ('<br>') cannot be used - it would show
    up as literal text - and the previous code added no separator at all, which ran every
    match into the next on a single line.
    """

    def test_xpath_multiple_matches_are_one_per_line(self):
        filtered = html_tools.xpath_filter(
            xpath_filter='//link/@href',
            html_content=LINK_PAGE,
            append_pretty_line_formatting=False,
        )

        self.assertNotIn('<br>', filtered, "'<br>' would leak into a source: snapshot as text")
        self.assertEqual(HREFS, filtered.splitlines())

    def test_xpath1_multiple_matches_are_one_per_line(self):
        filtered = html_tools.xpath1_filter(
            xpath_filter='//link/@href',
            html_content=LINK_PAGE,
            append_pretty_line_formatting=False,
        )

        self.assertNotIn('<br>', filtered)
        self.assertEqual(HREFS, filtered.splitlines())

    def test_css_multiple_matches_are_one_per_line(self):
        filtered = html_tools.include_filters(
            include_filters='link',
            html_content=LINK_PAGE,
            append_pretty_line_formatting=False,
        )

        self.assertNotIn('<br>', filtered)
        self.assertEqual(5, len(filtered.splitlines()))
        for href in HREFS:
            self.assertIn(href, filtered)

    def test_single_match_gets_no_separator(self):
        """One match means there is nothing to separate, so no leading newline either."""
        filtered = html_tools.xpath_filter(
            xpath_filter='//link[@rel="icon"]/@href',
            html_content=LINK_PAGE,
            append_pretty_line_formatting=False,
        )

        self.assertEqual('/static/favicon/wikipedia.ico', filtered)

    def test_no_matches_gets_empty_output(self):
        filtered = html_tools.xpath_filter(
            xpath_filter='//link[@rel="does-not-exist"]/@href',
            html_content=LINK_PAGE,
            append_pretty_line_formatting=False,
        )

        self.assertEqual('', filtered)


class TestFilterSeparatorHelper(unittest.TestCase):
    """The separator decision itself, including the unchanged Inscriptis path."""

    def test_first_match_never_gets_a_separator(self):
        for pretty in (True, False):
            self.assertEqual('', html_tools.filter_match_separator(pretty, "", None))
            self.assertEqual('', html_tools.filter_match_separator(pretty, "", 'div'))

    def test_pretty_path_keeps_using_the_br_marker(self):
        self.assertEqual(html_tools.TEXT_FILTER_LIST_LINE_SUFFIX,
                         html_tools.filter_match_separator(True, 'something', None))

    def test_pretty_path_leaves_tags_that_break_a_line_alone(self):
        for tag in html_tools.FILTER_TAGS_WITH_OWN_NEWLINE:
            self.assertEqual('', html_tools.filter_match_separator(True, 'something', tag))

    def test_non_pretty_path_uses_a_newline(self):
        self.assertEqual("\n", html_tools.filter_match_separator(False, 'something', None))
        # Even for tags that would break a line under Inscriptis - it never runs here, and a
        # '<br>' is not a newline in the verbatim text.
        self.assertEqual("\n", html_tools.filter_match_separator(False, 'something', 'div'))


if __name__ == '__main__':
    unittest.main()
