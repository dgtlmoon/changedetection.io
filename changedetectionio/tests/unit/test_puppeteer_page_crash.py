"""A renderer crash must stay local to the tab that crashed.

pyppeteer emits Page 'error' (``PageError('Page crashed!')``) when the renderer dies, and pyee
re-raises an 'error' emission that has no listener. That raise escapes into
``Connection._onMessage``, whose catch-all disposes the whole connection - so one dead tab takes
the browser with it and every later call reports the misleading "Session closed. Most likely the
page has been closed." ``fetch_page()`` attaches a listener to keep the failure local.
"""

import asyncio
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from loguru import logger
from pyee.asyncio import AsyncIOEventEmitter


class FakePage(AsyncIOEventEmitter):
    """Stands in for pyppeteer's Page, which is itself an AsyncIOEventEmitter."""

    def __init__(self):
        super().__init__()
        self.evaluate = AsyncMock(return_value='Mozilla/5.0')
        self.setUserAgent = AsyncMock()


def _fetch_page_until_csp(monkeypatch, page):
    """Drive fetch_page() up to the CSP step, then bail out and hand back the fetcher.

    The listener is attached straight after page creation, so aborting at the later CSP call
    is enough to get a fetcher wired to ``page``.
    """
    from changedetectionio.content_fetchers import puppeteer

    class StopAfterPageSetup(Exception):
        pass

    browser = SimpleNamespace(newPage=AsyncMock(return_value=page))
    pyppeteer_instance = SimpleNamespace(connect=AsyncMock(return_value=browser))

    pyppeteer_module = ModuleType('pyppeteer')
    pyppeteer_module.Pyppeteer = Mock(return_value=pyppeteer_instance)
    stealth_module = ModuleType('pyppeteerstealth')
    stealth_module.inject_evasions_into_page = AsyncMock()
    monkeypatch.setitem(sys.modules, 'pyppeteer', pyppeteer_module)
    monkeypatch.setitem(sys.modules, 'pyppeteerstealth', stealth_module)

    monkeypatch.setattr(
        puppeteer, '_configure_puppeteer_csp', AsyncMock(side_effect=StopAfterPageSetup)
    )

    f = puppeteer.fetcher()
    with pytest.raises(StopAfterPageSetup):
        asyncio.run(
            f.fetch_page(
                current_include_filters=None,
                empty_pages_are_a_change=False,
                fetch_favicon=False,
                ignore_status_codes=False,
                is_binary=False,
                request_body=None,
                request_headers={},
                request_method='GET',
                screenshot_format=None,
                timeout=45,
                url='https://example.com',
                watch_uuid='test-watch',
            )
        )
    return f


def test_page_crash_is_recorded_and_does_not_propagate(monkeypatch):
    page = FakePage()
    f = _fetch_page_until_csp(monkeypatch, page)

    assert f.page_errors == []

    crash = RuntimeError('Page crashed!')
    # No raise here is the whole point - an escaping raise is what disposed the connection
    page.emit('error', crash)

    assert f.page_errors == [crash]


def test_every_page_crash_in_one_load_is_kept(monkeypatch):
    """One load can crash more than one renderer - don't let the later error hide the first."""
    page = FakePage()
    f = _fetch_page_until_csp(monkeypatch, page)

    first = RuntimeError('iframe renderer gone')
    second = RuntimeError('Page crashed!')
    page.emit('error', first)
    page.emit('error', second)

    assert f.page_errors == [first, second]


def test_run_reports_page_errors_even_when_the_fetch_then_fails(monkeypatch):
    """Nothing consumes page_errors, so the log is the only signal - it must survive the raise."""
    from changedetectionio.content_fetchers import puppeteer

    f = puppeteer.fetcher()

    async def crashing_main(**kwargs):
        f.page_errors.append(RuntimeError('Page crashed!'))
        raise puppeteer.PageUnloadable(url='https://example.com', status_code=None, message='boom')

    monkeypatch.setattr(f, 'main', crashing_main)
    monkeypatch.setattr(f, 'quit', AsyncMock())

    records = []
    sink_id = logger.add(lambda m: records.append(m.record), level='WARNING')
    try:
        with pytest.raises(puppeteer.PageUnloadable):
            asyncio.run(f.run(url='https://example.com', watch_uuid='test-watch'))
    finally:
        logger.remove(sink_id)

    messages = [r['message'] for r in records if r['level'].name == 'WARNING']
    assert any('1 page error(s)' in m and 'Page crashed!' in m for m in messages), messages


def test_unlistened_page_crash_would_propagate():
    """Guards the premise above: without a listener, pyee hands the error straight back."""
    page = FakePage()

    with pytest.raises(RuntimeError, match='Page crashed!'):
        page.emit('error', RuntimeError('Page crashed!'))
