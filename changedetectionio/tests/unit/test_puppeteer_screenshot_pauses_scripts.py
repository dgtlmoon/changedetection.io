"""The puppeteer full page screenshot holds the page's own scripts still while a chunk is taken.

A page that animates repaints the whole (very tall) screenshot viewport on every frame and the
capture queues behind it, which on a busy browser used up the whole fetch. The scripts are paused
only around the capture itself, after the page had its chance to react to the new viewport size and
scroll position, and are always handed back.
"""

import asyncio
from types import SimpleNamespace

import pytest

from changedetectionio.content_fetchers import puppeteer

PAUSE = ('send', 'Emulation.setScriptExecutionDisabled', True)
RESUME = ('send', 'Emulation.setScriptExecutionDisabled', False)


def _fake_page(calls, page_height, screenshot_error=None, pause_error=None):
    async def evaluate(script, *args):
        if 'scrollHeight' in script:
            return page_height
        if 'scrollWidth' in script:
            return 1280
        if 'scrollTop' in script:
            calls.append(('scroll', args[0]))
        elif script == puppeteer.WAIT_FOR_NEXT_FRAME_JS:
            calls.append(('frame',))
        return None

    async def send(method, params=None):
        if method == 'Emulation.setScriptExecutionDisabled':
            if pause_error:
                raise pause_error
            calls.append(('send', method, params['value']))

    async def screenshot(**kwargs):
        calls.append(('screenshot',))
        if screenshot_error:
            raise screenshot_error
        return b'chunk'

    async def set_viewport(viewport):
        calls.append(('viewport', viewport['height']))

    return SimpleNamespace(viewport={'width': 1280, 'height': 800}, evaluate=evaluate, setViewport=set_viewport,
                           screenshot=screenshot, _client=SimpleNamespace(send=send))


@pytest.fixture(autouse=True)
def no_settle_time(monkeypatch):
    monkeypatch.setattr(puppeteer, 'SCREENSHOT_SETTLE_SECONDS', 0)


def test_scripts_are_paused_only_around_the_capture():
    calls = []
    asyncio.run(puppeteer.capture_full_page(_fake_page(calls, page_height=1500)))

    # Resized and scrolled first, the page renders that, and only then is it held still
    assert calls == [('viewport', 1500), ('scroll', 0), ('frame',), PAUSE, ('screenshot',), RESUME, ('viewport', 800)]


def test_page_that_fits_the_viewport_is_not_kept_waiting():
    calls = []
    asyncio.run(puppeteer.capture_full_page(_fake_page(calls, page_height=600)))

    # Nothing was resized, so there is nothing for the page to react to
    assert ('frame',) not in calls
    assert calls[-4:-1] == [PAUSE, ('screenshot',), RESUME]


def test_scripts_are_resumed_when_the_capture_fails():
    calls = []
    with pytest.raises(RuntimeError):
        asyncio.run(puppeteer.capture_full_page(_fake_page(calls, page_height=1500, screenshot_error=RuntimeError('Target closed'))))

    assert calls[-1] == RESUME, "A failed screenshot must not leave the page without its scripts"


def test_browser_that_cannot_pause_scripts_still_gets_a_screenshot():
    calls = []
    page = _fake_page(calls, page_height=1500, pause_error=Exception("'Emulation.setScriptExecutionDisabled' wasn't found"))

    assert asyncio.run(puppeteer.capture_full_page(page)) == b'chunk'
    assert ('screenshot',) in calls
