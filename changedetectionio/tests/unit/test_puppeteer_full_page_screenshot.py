"""The puppeteer full page screenshot: the first screen as it is, the rest in bands beyond the viewport.

The viewport is never resized and the page is never scrolled (both change how a page looks and what
it costs to draw), the page's own scripts are paused for the capture, very large canvases are left
blank below the first screen, and all of it is always handed back.
"""

import asyncio
import base64
from types import SimpleNamespace

import pytest

from changedetectionio.content_fetchers import puppeteer

PAUSE = ('scripts paused', True)
RESUME = ('scripts paused', False)


def _fake_page(calls, page_height, capture_error=None, pause_error=None, scrolled_to=0, large_canvases=0):
    async def evaluate(script, *args):
        if 'scrollHeight' in script:
            return page_height
        if 'scrollWidth' in script:
            return 1280
        if 'scrollY' in script:
            return scrolled_to
        if script == puppeteer.HIDE_LARGE_CANVASES_JS:
            assert args == (puppeteer.SCREENSHOT_MAX_CANVAS_PIXELS,)
            if large_canvases:
                calls.append(('large canvases hidden',))
            return large_canvases
        if script == puppeteer.RESTORE_LARGE_CANVASES_JS:
            calls.append(('large canvases shown again',))
            return None
        calls.append(('evaluate', script))
        return None

    async def send(method, params=None):
        if method == 'Emulation.setScriptExecutionDisabled':
            if pause_error:
                raise pause_error
            calls.append(('scripts paused', params['value']))
        elif method == 'Page.captureScreenshot':
            assert params['captureBeyondViewport'] is True
            calls.append(('band', params['clip']['y'], params['clip']['height'], params['clip']['width']))
            if capture_error:
                raise capture_error
            return {'data': base64.b64encode(b'band').decode()}
        return {}

    async def screenshot(**kwargs):
        calls.append(('viewport screenshot',))
        if capture_error:
            raise capture_error
        return b'viewport'

    async def set_viewport(viewport):
        calls.append(('viewport resized', viewport))

    return SimpleNamespace(viewport={'width': 1280, 'height': 800}, evaluate=evaluate, setViewport=set_viewport,
                           screenshot=screenshot, _client=SimpleNamespace(send=send),
                           _target=SimpleNamespace(_targetId='target'))


@pytest.fixture
def stitched(monkeypatch):
    """Keep the stitching subprocess out of it, hand back what it was given"""
    import multiprocessing
    import struct

    def worker(pipe_conn, original_page_height, capture_height):
        count = struct.unpack('I', pipe_conn.recv_bytes())[0]
        pipe_conn.send_bytes(b'+'.join(pipe_conn.recv_bytes() for _ in range(count)))

    class InProcess:
        def __init__(self, target, args):
            self.target, self.args = target, args

        def start(self):
            import threading
            self.thread = threading.Thread(target=worker, args=self.args)
            self.thread.start()

        def join(self):
            self.thread.join()

    context = SimpleNamespace(Pipe=multiprocessing.Pipe, Process=InProcess)
    monkeypatch.setattr(multiprocessing, 'get_context', lambda method: context)


def test_tall_page_is_the_first_screen_then_bands_without_touching_the_viewport(stitched):
    calls = []
    screenshot = asyncio.run(puppeteer.capture_full_page(_fake_page(calls, page_height=14691)))

    # Paused for the whole capture, the bands start under the first screen and end with the page
    assert calls == [PAUSE, ('viewport screenshot',), ('band', 800, 10000, 1280), ('band', 10800, 3891, 1280), RESUME]
    assert screenshot == b'viewport+band+band'


def test_page_that_is_not_at_the_top_is_all_bands(stitched):
    calls = []
    asyncio.run(puppeteer.capture_full_page(_fake_page(calls, page_height=14691, scrolled_to=300)))

    # The first screen would not be the top of the page
    assert calls == [PAUSE, ('band', 0, 10000, 1280), ('band', 10000, 4691, 1280), RESUME]


def test_very_large_canvases_are_blank_only_below_the_first_screen(stitched):
    calls = []
    asyncio.run(puppeteer.capture_full_page(_fake_page(calls, page_height=5000, large_canvases=2)))

    assert calls == [PAUSE, ('viewport screenshot',), ('large canvases hidden',), ('band', 800, 4200, 1280),
                     ('large canvases shown again',), RESUME]


def test_page_longer_than_the_limit_is_cut_off_at_it(stitched, monkeypatch):
    monkeypatch.setattr(puppeteer, 'SCREENSHOT_MAX_TOTAL_HEIGHT', 12000)
    calls = []
    asyncio.run(puppeteer.capture_full_page(_fake_page(calls, page_height=50000)))

    assert [c for c in calls if c[0] == 'band'] == [('band', 800, 10000, 1280), ('band', 10800, 1200, 1280)]


def test_page_that_fits_the_viewport_is_one_plain_screenshot():
    calls = []
    assert asyncio.run(puppeteer.capture_full_page(_fake_page(calls, page_height=600, large_canvases=1))) == b'viewport'

    assert calls == [PAUSE, ('viewport screenshot',), RESUME]


def test_everything_is_handed_back_when_the_capture_fails():
    calls = []
    page = _fake_page(calls, page_height=1500, scrolled_to=10, large_canvases=1, capture_error=RuntimeError('Target closed'))
    with pytest.raises(RuntimeError):
        asyncio.run(puppeteer.capture_full_page(page))

    assert calls[-2:] == [('large canvases shown again',), RESUME], \
        "A failed screenshot must not leave the page without its scripts or its canvases"


def test_browser_that_cannot_pause_scripts_still_gets_a_screenshot(stitched):
    calls = []
    page = _fake_page(calls, page_height=1500, pause_error=Exception("'Emulation.setScriptExecutionDisabled' wasn't found"))

    assert asyncio.run(puppeteer.capture_full_page(page)) == b'viewport+band'
    assert calls == [('viewport screenshot',), ('band', 800, 700, 1280)]


def test_resuming_scripts_does_not_wait_on_a_browser_that_stopped_answering(monkeypatch):
    monkeypatch.setattr(puppeteer, 'RESUME_PAGE_SCRIPTS_TIMEOUT_SECONDS', 0.05)

    async def send(method, params=None):
        await asyncio.sleep(3600)

    page = SimpleNamespace(_client=SimpleNamespace(send=send))

    async def resume():
        return await asyncio.wait_for(puppeteer._set_page_scripts_paused(page, False), timeout=2)

    assert asyncio.run(resume()) is False
