"""A full page screenshot of a browser that runs WITHOUT viewport emulation.

A browser launched at its real window size (maximized, as a plugin's browser may be by default)
reports page.viewport_size as None. capture_full_page_async() assumed there always is one and
failed every check with "'NoneType' object is not subscriptable".
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock


def _page(viewport_size, page_height, window=(1920, 1080)):
    """A stand-in Playwright page of the given height. Records what it is asked."""
    evaluated = []

    async def evaluate(script, *args):
        evaluated.append(script)
        if 'scrollHeight' in script:
            return page_height
        if 'scrollWidth' in script:
            return window[0]
        if 'innerWidth' in script:
            return {'width': window[0], 'height': window[1]}
        return None

    page = SimpleNamespace(
        viewport_size=viewport_size,
        evaluate=evaluate,
        set_viewport_size=AsyncMock(),
        request_gc=AsyncMock(),
        screenshot=AsyncMock(return_value=b'screenshot'),
    )
    return page, evaluated


def _capture(page, **kwargs):
    from changedetectionio.content_fetchers.playwright import capture_full_page_async
    return asyncio.run(capture_full_page_async(page, **kwargs))


def test_no_viewport_and_a_page_that_fits_the_window():
    """Nothing to step through: one screenshot, and viewport emulation is never switched on."""
    page, evaluated = _page(viewport_size=None, page_height=900)
    assert _capture(page) == b'screenshot'
    assert any('innerWidth' in script for script in evaluated), "the window's own size is asked for"
    page.set_viewport_size.assert_not_called()
    assert page.screenshot.await_count == 1


def test_no_viewport_and_a_page_taller_than_the_window():
    """Stepped through at the window's width, then put back to the window's size."""
    page, _evaluated = _page(viewport_size=None, page_height=1500)
    assert _capture(page) == b'screenshot'
    calls = [call.args[0] for call in page.set_viewport_size.await_args_list]
    # Taller viewport to capture with (the page is under the stitch threshold, so its full height)...
    assert calls[0] == {'width': 1920, 'height': 1500}
    # ...and back to what the window was
    assert calls[-1] == {'width': 1920, 'height': 1080}
    assert len(calls) == 2


def test_no_viewport_with_element_locking():
    page, evaluated = _page(viewport_size=None, page_height=1500)
    assert _capture(page, lock_viewport_elements=True) == b'screenshot'
    assert any('lock' in script.lower() for script in evaluated)


def test_an_emulated_viewport_behaves_as_before():
    """The usual case is untouched: the page's own viewport is used and always restored, and the
    window size is never asked for."""
    for page_height, expected in (
        (600, [{'width': 1280, 'height': 800}]),
        (1500, [{'width': 1280, 'height': 1500}, {'width': 1280, 'height': 800}]),
    ):
        page, evaluated = _page(viewport_size={'width': 1280, 'height': 800}, page_height=page_height)
        assert _capture(page) == b'screenshot'
        assert not any('innerWidth' in script for script in evaluated)
        assert [call.args[0] for call in page.set_viewport_size.await_args_list] == expected
