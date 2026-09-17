#!/usr/bin/env python3
# coding=utf-8

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_content_type_detection

"""Unit tests for guess_stream_type() content-type classification.

Regression cover for #4302: a normal HTML page served as 'text/html;charset=utf-8' was
classified as plaintext, which made processor.py skip html_to_text() entirely and store the
raw filtered block as the snapshot (visible as literal '<br>' separators in every diff).

Two independent failures had to line up:
  1. The header test was an exact comparison ("text/html"), so any charset parameter missed it.
  2. has_html_patterns only sniffs content[:200], and the page put 241 bytes of HTML comments
     before <!DOCTYPE, so the content sniff could not rescue it either.
Falling through both landed on the `startswith('text/')` catch-all -> is_plaintext.
"""

import unittest

from changedetectionio.processors.magic import guess_stream_type

# Real-world shape from https://www.newbalancemexico.com/c/lo-mas-nuevo (Salesforce/ISML templates):
# blank lines and two long comments push <!DOCTYPE past the 200-byte sniff window.
COMMENT_PREAMBLE_HTML = (
    "\n\n\n\n\n\n"
    "<!-- Include Page Designer Campaign Banner JavaScript and Styles only once here rather than"
    " at component level. -->\n"
    "<!-- There should only be one Campagin Banner added on a PD page. Multiple Banners is"
    " unsupported at the moment. -->\n\n\n"
    '<!DOCTYPE html>\n<html lang="es">\n<head>\n<script>//common/scripts.isml</script>\n</head>\n'
    '<body><div class="product" data-pid="U204LMMA"></div></body></html>'
)

PLAIN_HTML = '<!DOCTYPE html><html><head><title>t</title></head><body><p>hi</p></body></html>'


class TestGuessStreamType(unittest.TestCase):

    def _flags(self, header, content):
        st = guess_stream_type(http_content_header=header, content=content)
        return {n: getattr(st, n) for n in
                ('is_html', 'is_plaintext', 'is_rss', 'is_xml', 'is_json', 'is_pdf', 'is_csv')}

    def test_preamble_pushes_doctype_past_sniff_window(self):
        # Guard the premise of the test below - if this ever shrinks, the regression case is no
        # longer exercising the "content sniff cannot help" path.
        self.assertGreater(COMMENT_PREAMBLE_HTML.index('<!DOCTYPE'), 200,
                           "Test fixture must keep <!DOCTYPE outside the 200 byte sniff window")

    def test_html_with_charset_param_is_html_not_plaintext(self):
        """#4302 - the exact regression. 'text/html' + charset must never be plaintext."""
        # Note: guess_stream_type expects an already-lowercased header (processor.py lowercases it).
        for header in ('text/html;charset=utf-8',
                       'text/html; charset=utf-8',
                       'text/html ; charset=utf-8',
                       'text/html'):
            with self.subTest(header=header):
                f = self._flags(header, COMMENT_PREAMBLE_HTML)
                self.assertTrue(f['is_html'], f"{header!r} should be HTML, got {f}")
                self.assertFalse(f['is_plaintext'],
                                 f"{header!r} must not be plaintext - processor.py checks "
                                 f"is_plaintext before is_html and would skip html_to_text")

    def test_html_detected_by_content_when_header_is_useless(self):
        """No/garbage header still works when the sniff window can see the markup."""
        for header in ('', 'application/octet-stream'):
            with self.subTest(header=header):
                self.assertTrue(self._flags(header, PLAIN_HTML)['is_html'])

    def test_real_plaintext_still_plaintext(self):
        f = self._flags('text/plain;charset=utf-8', 'Just some plain text, no markup here at all.\n')
        self.assertTrue(f['is_plaintext'])
        self.assertFalse(f['is_html'])

    def test_content_evidence_still_beats_the_header(self):
        """The ordering in guess_stream_type is deliberate: servers lie with 'text/html'.

        These must keep winning over the header, otherwise RSS loses its CDATA handling and
        JSON loses reformatting. See magic.py:86 - puremagic's verdict is trusted for every
        type *except* text/html and text/plain, for exactly this reason.
        """
        rss = '<?xml version="1.0"?>\n<rss version="2.0"><channel><title>f</title></channel></rss>'
        atom = '<?xml version="1.0"?>\n<feed xmlns="http://www.w3.org/2005/Atom"><title>f</title></feed>'
        json_doc = '{"title": "hello", "items": [1, 2, 3]}'

        self.assertTrue(self._flags('text/html;charset=utf-8', rss)['is_rss'])
        self.assertTrue(self._flags('text/html;charset=utf-8', atom)['is_rss'])
        self.assertTrue(self._flags('application/json', json_doc)['is_json'])
        self.assertTrue(self._flags('text/xml', '<?xml version="1.0"?><catalog><i>x</i></catalog>')['is_xml'])


class TestFilterSeparatorSurvivesTextExtraction(unittest.TestCase):
    """#4302 end to end: an attribute xpath must produce newlines, never a literal '<br>'.

    xpath_filter injects TEXT_FILTER_LIST_LINE_SUFFIX ('<br>') between matches that have no
    .tag attribute - i.e. attribute and text() nodes, which is precisely when the filter output
    is no longer HTML. That marker is only removed if html_to_text() runs, so this test pins the
    classification and the conversion together.
    """

    def test_attribute_xpath_matches_become_newlines(self):
        from changedetectionio import html_tools

        filtered = html_tools.xpath_filter(
            xpath_filter='//div[@class="product"]/@data-pid',
            html_content=COMMENT_PREAMBLE_HTML.replace(
                '<div class="product" data-pid="U204LMMA"></div>',
                '<div class="product" data-pid="U204LMMA"></div>'
                '<div class="product" data-pid="MR530KA"></div>'),
            append_pretty_line_formatting=True,
        )
        # The marker is expected at this stage - it is an intermediate value, not a snapshot.
        self.assertIn('<br>', filtered)

        stream = guess_stream_type(http_content_header='text/html;charset=utf-8',
                                   content=COMMENT_PREAMBLE_HTML)
        self.assertTrue(stream.is_html)
        self.assertFalse(stream.is_plaintext)

        text = html_tools.html_to_text(html_content=filtered, is_rss=stream.is_rss)
        self.assertNotIn('<br>', text, "'<br>' leaked into the snapshot - see #4302")
        self.assertIn('U204LMMA', text)
        self.assertIn('MR530KA', text)
        self.assertEqual(['U204LMMA', 'MR530KA'], text.split())


if __name__ == '__main__':
    # Can run this file directly for quick testing
    unittest.main()
