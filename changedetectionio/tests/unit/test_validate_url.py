#!/usr/bin/env python3

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_validate_url

import unittest

from changedetectionio.validate_url import is_safe_valid_url, normalize_url_encoding


class TestValidateUrl(unittest.TestCase):

    def test_fragment_with_pipe_characters_is_valid(self):
        """https://github.com/dgtlmoon/changedetection.io/issues/4209
        Browsers accept '|' in the fragment/anchor but RFC 3986 does not,
        so it must be percent-encoded before validation instead of rejected."""
        url = 'https://www.fnac.com/Pack-Tablette-Tactile-Samsung-Galaxy-Tab-S10-Lite-10-9-Wi-Fi-128-Go-Anthracite-Book-Cover/a21903823/w-4#int=S:PFreco|PF|48966|21903823|BL4|L1'
        self.assertTrue(is_safe_valid_url(url), f"URL '{url}' with '|' in the fragment should be valid")

    def test_fragment_pipe_is_percent_encoded(self):
        normalized = normalize_url_encoding('https://example.com/page#a|b')
        self.assertEqual(normalized, 'https://example.com/page#a%7Cb')

    def test_already_encoded_fragment_is_not_double_encoded(self):
        normalized = normalize_url_encoding('https://example.com/page#a%7Cb')
        self.assertEqual(normalized, 'https://example.com/page#a%7Cb')

    def test_fragment_normalization_is_idempotent(self):
        url = 'https://example.com/page#int=S:PFreco|PF|48966'
        once = normalize_url_encoding(url)
        twice = normalize_url_encoding(once)
        self.assertEqual(once, twice)

    def test_rfc3986_fragment_characters_are_untouched(self):
        # pchar / "/" / "?" are all legal in a fragment and must survive as-is
        urls = [
            'https://example.com/docs#section-2.1',
            'https://example.com/app#/route/sub?tab=1',
            "https://example.com/page#key=val&other=a:b@c!$&'()*+,;=",
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(normalize_url_encoding(url), url)
                self.assertTrue(is_safe_valid_url(url))

    def test_unsafe_urls_are_still_rejected(self):
        # The fragment fix must not loosen any of the existing security checks
        unsafe = [
            'javascript:alert(1)',
            'source:javascript:alert(1)',
            'https://example.com/page#<script>',
            'http://INTERNAL:8888\\@PUBLIC/',
            '',
            None,
        ]
        for url in unsafe:
            with self.subTest(url=url):
                self.assertFalse(is_safe_valid_url(url), f"URL '{url}' should be rejected")


if __name__ == '__main__':
    unittest.main()
