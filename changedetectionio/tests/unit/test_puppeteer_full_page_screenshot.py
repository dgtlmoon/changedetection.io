"""The puppeteer full page screenshot: bands captured beyond the viewport, with the page held still.

The viewport is never resized and the page is never scrolled (both change how a page looks and what
it costs to draw), and the page's own scripts are paused for the capture and always handed back.
"""

import asyncio
import base64
from types import SimpleNamespace

import pytest

from changedetectionio.content_fetchers import puppeteer

PAUSE = ('scripts paused', True)
RESUME = ('scripts paused', False)


def _fake_page(calls, page_height, capture_error=None, pause_error=None):
    async def evaluate(script, *args):
        if 'scrollHeight' in script:
            return page_height
        if 'scrollWidth' in script:
            return 1280
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


def test_tall_page_is_captured_in_bands_without_touching_the_viewport(stitched):
    calls = []
    screenshot = asyncio.run(puppeteer.capture_full_page(_fake_page(calls, page_height=14691)))

    # Paused for the whole capture, the last band is only what is left of the page
    assert calls == [PAUSE, ('band', 0, 10000, 1280), ('band', 10000, 4691, 1280), RESUME]
    assert screenshot == b'band+band'


def test_page_longer_than_the_limit_is_cut_off_at_it(stitched, monkeypatch):
    monkeypatch.setattr(puppeteer, 'SCREENSHOT_MAX_TOTAL_HEIGHT', 12000)
    calls = []
    asyncio.run(puppeteer.capture_full_page(_fake_page(calls, page_height=50000)))

    assert [c for c in calls if c[0] == 'band'] == [('band', 0, 10000, 1280), ('band', 10000, 2000, 1280)]


def test_page_that_fits_the_viewport_is_one_plain_screenshot():
    calls = []
    assert asyncio.run(puppeteer.capture_full_page(_fake_page(calls, page_height=600))) == b'viewport'

    assert calls == [PAUSE, ('viewport screenshot',), RESUME]


def test_scripts_are_resumed_when_the_capture_fails():
    calls = []
    with pytest.raises(RuntimeError):
        asyncio.run(puppeteer.capture_full_page(_fake_page(calls, page_height=1500, capture_error=RuntimeError('Target closed'))))

    assert calls[-1] == RESUME, "A failed screenshot must not leave the page without its scripts"


def test_browser_that_cannot_pause_scripts_still_gets_a_screenshot():
    calls = []
    page = _fake_page(calls, page_height=1500, pause_error=Exception("'Emulation.setScriptExecutionDisabled' wasn't found"))

    assert asyncio.run(puppeteer.capture_full_page(page)) == b'band'
    assert calls == [('band', 0, 1500, 1280)]


def test_resuming_scripts_does_not_wait_on_a_browser_that_stopped_answering(monkeypatch):
    monkeypatch.setattr(puppeteer, 'RESUME_PAGE_SCRIPTS_TIMEOUT_SECONDS', 0.05)

    async def send(method, params=None):
        await asyncio.sleep(3600)

    page = SimpleNamespace(_client=SimpleNamespace(send=send))

    async def resume():
        return await asyncio.wait_for(puppeteer._set_page_scripts_paused(page, False), timeout=2)

    assert asyncio.run(resume()) is False
