#!/usr/bin/env python3

# run from dir above changedetectionio/ dir
# python3 -m pytest changedetectionio/tests/unit/test_fetcher_capabilities.py
#
# Regression tests for fetcher capability resolution of the "extra browser" and
# "extra playwright server" fetch-backend prefixes.
#
# A watch's fetch_backend can be "extra_browser_<name>" or
# "extra_playwright_server_<name>". These are routed to a real browser fetcher in
# processors/base.py, but the capability lookups used to match them against the
# fetcher registry verbatim, find nothing, and report no capabilities at all -
# so the preview "Current screenshot" tab wrongly claimed the fetcher could not
# take screenshots even though one had been captured.

from changedetectionio.pluggy_interface import get_fetcher_capabilities
from changedetectionio.model import Watch


class _MockDatastore:
    """Minimal datastore stub. get_fetcher_capabilities only reads
    .data['settings']['application'] and only when resolving 'system'."""

    def __init__(self, system_fetch_backend='html_requests'):
        self.data = {'settings': {'application': {'fetch_backend': system_fetch_backend}}}


def _caps(fetch_backend, system_fetch_backend='html_requests'):
    return get_fetcher_capabilities({'fetch_backend': fetch_backend},
                                    _MockDatastore(system_fetch_backend))


def test_extra_playwright_server_supports_screenshots():
    # extra_playwright_server_* is force-routed to the Playwright fetcher in
    # processors/base.py, which supports screenshots, browser steps and xpath.
    caps = _caps('extra_playwright_server_My Server')
    assert caps['supports_screenshots'] is True
    assert caps['supports_browser_steps'] is True
    assert caps['supports_xpath_element_data'] is True


def test_extra_browser_supports_screenshots():
    # extra_browser_* routes to the configured webdriver/chrome fetcher; every
    # browser fetcher (playwright/puppeteer/selenium) supports screenshots.
    assert _caps('extra_browser_BrightData')['supports_screenshots'] is True


def test_unknown_backend_reports_no_capabilities():
    assert _caps('this_is_not_a_real_fetcher') == {
        'supports_browser_steps': False,
        'supports_screenshots': False,
        'supports_xpath_element_data': False,
    }


def test_plain_requests_backend_has_no_screenshots():
    assert _caps('html_requests')['supports_screenshots'] is False


def _make_watch(fetch_backend):
    watch = Watch.model(datastore_path='/tmp',
                        __datastore={'settings': {'application': {}}, 'watching': {}},
                        default={})
    watch['url'] = 'https://example.com'
    watch['fetch_backend'] = fetch_backend
    return watch


def test_watch_property_resolves_extra_playwright_server():
    assert _make_watch('extra_playwright_server_My Server').fetcher_supports_screenshots is True


def test_watch_property_resolves_extra_browser():
    assert _make_watch('extra_browser_BrightData').fetcher_supports_screenshots is True


def test_watch_property_plain_requests_no_screenshots():
    assert _make_watch('html_requests').fetcher_supports_screenshots is False
