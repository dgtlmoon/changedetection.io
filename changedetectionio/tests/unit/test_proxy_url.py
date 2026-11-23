#!/usr/bin/env python3

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_proxy_url

import unittest

from changedetectionio.proxy_url import proxy_credentials, redact_proxy_url


class TestProxyCredentials(unittest.TestCase):
    def test_percent_encoded_credentials_are_decoded(self):
        # 'p#ss/w?rd@1%' encoded, as the proxy settings ask for special characters
        url = "http://customer-user:p%23ss%2Fw%3Frd%401%25@proxy.example.com:7777"
        self.assertEqual(proxy_credentials(url), ("customer-user", "p#ss/w?rd@1%"))

    def test_plain_credentials_are_unchanged(self):
        self.assertEqual(proxy_credentials("http://user:pass@proxy.example.com:8080"), ("user", "pass"))

    def test_no_credentials(self):
        self.assertEqual(proxy_credentials("http://proxy.example.com:8080"), (None, None))
        self.assertEqual(proxy_credentials(None), (None, None))

    def test_username_only(self):
        self.assertEqual(proxy_credentials("socks5://user@proxy.example.com:1080"), ("user", None))


class TestRedactProxyUrl(unittest.TestCase):
    def test_credentials_are_removed(self):
        url = "http://customer-user:p%23ss@proxy.example.com:7777"
        self.assertEqual(redact_proxy_url(url), "http://***@proxy.example.com:7777")

    def test_unencoded_special_characters_do_not_leak(self):
        redacted = redact_proxy_url("http://customer-user:pppppp##@pr.example.com:7777")
        self.assertEqual(redacted, "http://***@pr.example.com:7777")
        redacted = redact_proxy_url("http://user:p@ss@proxy.example.com:8080")
        self.assertEqual(redacted, "http://***@proxy.example.com:8080")

    def test_url_without_credentials_is_unchanged(self):
        self.assertEqual(redact_proxy_url("socks5://proxy.example.com:1080"), "socks5://proxy.example.com:1080")
        self.assertIsNone(redact_proxy_url(None))


if __name__ == '__main__':
    unittest.main()
