#!/usr/bin/env python3

"""Tests for the shared "may the server fetch this URL?" gate.

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_fetch_url_gate

Every server-side fetch entry point routes through validate_url.is_fetch_url_allowed(). Before it
existed, the file:// and private-IP rules were enforced inline in call_browser() only, so any fetch
path that did not go through call_browser() was unprotected:

  * a "Goto URL" browser step could read file:///etc/passwd     (GHSA-hm22-wg2m-35v4)
  * /add-watch-ui/snapshot url= could fetch internal hosts       (GHSA-56fq-63vj-9992)

These tests pin the gate's rules AND the browser-step choke point, so a future fetch path that
forgets to call the gate is the only way to regress it.
"""

import asyncio
import unittest
from unittest.mock import patch

from changedetectionio.browser_steps.browser_steps import steppable_browser_interface
from changedetectionio.validate_url import (
    is_fetch_url_allowed,
    is_special_purpose_ip,
    validate_fetch_url,
    validate_fetch_url_async,
)

# tests/conftest.py sets ALLOW_IANA_RESTRICTED_ADDRESSES=true for the functional suite, so the
# locked-down default has to be re-asserted explicitly rather than assumed.
LOCKED_DOWN = {'ALLOW_IANA_RESTRICTED_ADDRESSES': 'false', 'ALLOW_FILE_URI': 'false'}
OPTED_IN = {'ALLOW_IANA_RESTRICTED_ADDRESSES': 'true', 'ALLOW_FILE_URI': 'true'}


class TestFetchUrlGate(unittest.TestCase):

    def assertBlocked(self, url):
        ok, reason = is_fetch_url_allowed(url)
        self.assertFalse(ok, f"URL '{url}' should have been blocked")
        self.assertTrue(reason, f"URL '{url}' was blocked without a reason to show the user")

    def assertAllowed(self, url):
        ok, reason = is_fetch_url_allowed(url)
        self.assertTrue(ok, f"URL '{url}' should have been allowed, got: {reason}")

    def test_file_uri_blocked_by_default(self):
        with patch.dict('os.environ', LOCKED_DOWN):
            # All the spellings that reach the same local file
            for url in ('file:///etc/passwd', 'FILE:///etc/passwd', 'file:/etc/passwd', 'file://etc/passwd'):
                with self.subTest(url=url):
                    self.assertBlocked(url)

    def test_file_uri_allowed_when_operator_opts_in(self):
        with patch.dict('os.environ', OPTED_IN):
            self.assertAllowed('file:///etc/passwd')

    def test_file_uri_blocked_even_if_safe_protocol_regex_was_loosened(self):
        """An operator who widens SAFE_PROTOCOL_REGEX for some other scheme must not get local
        file reads thrown in for free - hence the explicit file: check ahead of is_safe_valid_url()."""
        env = dict(LOCKED_DOWN, SAFE_PROTOCOL_REGEX='^(http|https|ftp|file):')
        with patch.dict('os.environ', env):
            self.assertBlocked('file:///etc/passwd')

    def test_private_and_reserved_addresses_blocked_by_default(self):
        with patch.dict('os.environ', LOCKED_DOWN):
            for url in ('http://127.0.0.1:5000/',
                        'http://localhost/',
                        'http://169.254.169.254/latest/meta-data/',  # cloud metadata
                        'http://192.168.1.1/',
                        'http://10.0.0.1/',
                        'http://[::1]/'):
                with self.subTest(url=url):
                    self.assertBlocked(url)

    def test_cgnat_and_other_non_global_addresses_blocked_by_default(self):
        """GHSA-gwph-fp79-379w - the 0.54.1 predicate only tested is_private/is_loopback/
        is_link_local/is_reserved, none of which are True for RFC 6598 CGNAT space, so
        100.64.0.0/10 (an ISP's other subscribers, CPE admin panels, CGNAT gateways) stayed
        fetchable. These are IP literals, so no DNS is involved and CI cannot flake."""
        with patch.dict('os.environ', LOCKED_DOWN):
            for url in ('http://100.64.0.1/',            # RFC 6598 CGNAT, first usable
                        'http://100.127.255.254/',       # RFC 6598 CGNAT, last usable
                        'http://100.100.100.100/',       # inside CGNAT (Alibaba Cloud metadata)
                        'http://192.88.99.1/',           # RFC 7526 deprecated 6to4 relay anycast
                        'http://224.0.0.1/',             # IPv4 multicast all-hosts
                        'http://[ff02::1]/'):            # IPv6 multicast all-nodes
                with self.subTest(url=url):
                    self.assertBlocked(url)

    def test_cgnat_allowed_when_operator_opts_in(self):
        """CGNAT is legitimate for operators monitoring their own carrier network, so the
        opt-in has to release it the same way it releases 127.0.0.1."""
        with patch.dict('os.environ', OPTED_IN):
            self.assertAllowed('http://100.64.0.1/')

    def test_special_purpose_ip_classification(self):
        """The predicate itself, without DNS - one place to pin what is and is not fetchable."""
        for ip in ('100.64.0.1', '100.127.255.254', '192.88.99.1', '224.0.0.1', 'ff02::1',
                   '127.0.0.1', '10.0.0.1', '169.254.169.254', '192.168.1.1', '::1',
                   '0.0.0.0', '255.255.255.255', '198.18.0.1', 'fc00::1', 'fe80::1',
                   '::ffff:100.64.0.1',   # CGNAT wrapped as an IPv4-mapped IPv6 address
                   '2002:6440:1::'):      # CGNAT wrapped as a 6to4 address
            with self.subTest(ip=ip):
                blocked, why = is_special_purpose_ip(ip)
                self.assertTrue(blocked, f"{ip} should be refused")
                self.assertTrue(why, f"{ip} was refused without a stated reason")

        for ip in ('1.1.1.1', '8.8.8.8', '93.184.216.34', '2606:4700:4700::1111'):
            with self.subTest(ip=ip):
                blocked, why = is_special_purpose_ip(ip)
                self.assertFalse(blocked, f"public address {ip} was refused as '{why}'")

    def test_cgnat_boundaries_are_exact(self):
        """100.64.0.0/10 ends at 100.127.255.255 - 100.63.x and 100.128.x are ordinary public
        space and must not be collateral damage from a /8-sized over-block."""
        for ip in ('100.63.255.255', '100.128.0.0'):
            with self.subTest(ip=ip):
                blocked, why = is_special_purpose_ip(ip)
                self.assertFalse(blocked, f"public address {ip} was refused as '{why}'")

    def test_private_addresses_allowed_when_operator_opts_in(self):
        with patch.dict('os.environ', OPTED_IN):
            self.assertAllowed('http://127.0.0.1:5000/')

    def test_source_prefix_is_stripped_before_the_hostname_check(self):
        """Load-bearing, not cosmetic: urlparse('source:http://127.0.0.1/') reports NO hostname,
        so leaving the prefix on would hand the private-IP check nothing to look at and let it pass."""
        with patch.dict('os.environ', LOCKED_DOWN):
            self.assertBlocked('source:http://127.0.0.1/')
            self.assertBlocked('SOURCE:http://169.254.169.254/')
            self.assertBlocked('source:file:///etc/passwd')

    def test_jinja2_is_rendered_before_the_hostname_check(self):
        """The fetch uses the rendered URL, so the rendered URL is what must be judged - otherwise
        a template expression hides the real target from the check."""
        with patch.dict('os.environ', LOCKED_DOWN):
            self.assertBlocked("http://{{ '127.0.0.1' }}/")
            self.assertBlocked("http://{% if 1 %}127.0.0.1{% endif %}/")

    def test_parser_differential_payload_always_rejected(self):
        """GHSA-rph4-96w6-q594: urlparse sees PUBLIC, urllib3 connects to INTERNAL. A backslash has
        no legitimate use in a URL, so this is refused even with both opt-ins enabled."""
        for env in (LOCKED_DOWN, OPTED_IN):
            with self.subTest(env=env), patch.dict('os.environ', env):
                self.assertBlocked('http://127.0.0.1:8888\\@example.com/')

    def test_unsupported_schemes_rejected(self):
        with patch.dict('os.environ', LOCKED_DOWN):
            for url in ('javascript:alert(1)', 'data:text/html,<h1>x', 'chrome://version'):
                with self.subTest(url=url):
                    self.assertBlocked(url)

    def test_empty_input_rejected(self):
        with patch.dict('os.environ', LOCKED_DOWN):
            for url in ('', '   ', None):
                with self.subTest(url=url):
                    self.assertBlocked(url)

    def test_ordinary_public_urls_still_allowed(self):
        # Unresolvable hostnames are allowed by design (DNS may be down, domain not yet live), so
        # these pass with or without working DNS in CI.
        with patch.dict('os.environ', LOCKED_DOWN):
            for url in ('https://example.com/',
                        'source:https://example.com/',
                        'https://example.com/path?a=b&c=d#frag'):
                with self.subTest(url=url):
                    self.assertAllowed(url)

    def test_validate_fetch_url_raises_with_the_reason(self):
        with patch.dict('os.environ', LOCKED_DOWN):
            with self.assertRaises(ValueError):
                validate_fetch_url('file:///etc/passwd')
            validate_fetch_url('https://example.com/')  # must not raise

    def test_validate_fetch_url_async_raises_with_the_reason(self):
        with patch.dict('os.environ', LOCKED_DOWN):
            with self.assertRaises(ValueError):
                asyncio.run(validate_fetch_url_async('http://127.0.0.1/'))
            asyncio.run(validate_fetch_url_async('https://example.com/'))  # must not raise


class _RecordingPage:
    """Stands in for the Playwright page so we can assert navigation never happened."""

    def __init__(self):
        self.goto_calls = []

    async def goto(self, url, **kwargs):
        self.goto_calls.append(url)
        return None

    async def wait_for_timeout(self, ms):
        return None


class TestBrowserStepGotoUrlGate(unittest.TestCase):
    """GHSA-hm22-wg2m-35v4 - browser step values are raw user input and were never validated.

    action_goto_url() is the single choke point for every navigation we initiate (the "Goto URL"
    step, "Goto site", the live Browser Steps UI and the Add Watch preview all land here), so the
    assertion that matters is that page.goto() is never reached for a refused URL.
    """

    def _interface(self, start_url='https://example.com/'):
        interface = steppable_browser_interface(start_url=start_url)
        interface.page = _RecordingPage()
        return interface

    def test_goto_url_step_cannot_read_local_files(self):
        with patch.dict('os.environ', LOCKED_DOWN):
            interface = self._interface()
            with self.assertRaises(ValueError):
                asyncio.run(interface.action_goto_url(value='file:///etc/passwd'))
            self.assertEqual(interface.page.goto_calls, [], "Chromium was navigated to a refused URL")

    def test_goto_url_step_cannot_reach_private_addresses(self):
        with patch.dict('os.environ', LOCKED_DOWN):
            for url in ('http://127.0.0.1:5000/', 'http://169.254.169.254/latest/meta-data/'):
                with self.subTest(url=url):
                    interface = self._interface()
                    with self.assertRaises(ValueError):
                        asyncio.run(interface.action_goto_url(value=url))
                    self.assertEqual(interface.page.goto_calls, [])

    def test_goto_site_step_validates_the_start_url_too(self):
        with patch.dict('os.environ', LOCKED_DOWN):
            interface = self._interface(start_url='source:http://127.0.0.1/')
            with self.assertRaises(ValueError):
                asyncio.run(interface.action_goto_site())
            self.assertEqual(interface.page.goto_calls, [])

    def test_permitted_url_still_navigates(self):
        with patch.dict('os.environ', LOCKED_DOWN):
            interface = self._interface()
            asyncio.run(interface.action_goto_url(value='https://example.com/'))
            self.assertEqual(interface.page.goto_calls, ['https://example.com/'])


if __name__ == '__main__':
    unittest.main()
