"""The element locking scripts must be read as UTF-8 on every platform.

lock-elements-sizing.js and unlock-elements-sizing.js contain non-ASCII characters
("→", "⚠"). Reading them with the locale encoding failed with a UnicodeDecodeError
on Windows with a legacy code page such as cp932, so every full page screenshot
with element locking enabled failed there.
"""

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

RES_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'content_fetchers', 'res')


def _read_res(name):
    with open(os.path.join(RES_DIR, name), encoding='utf-8') as f:
        return f.read()


def _fake_evaluate(scripts):
    async def evaluate(script, *args):
        scripts.append(script)
        if 'scrollHeight' in script:
            return 1500
        if 'scrollWidth' in script:
            return 1280
        return None

    return evaluate


def _assert_locking_scripts_evaluated(scripts):
    lock_js = _read_res('lock-elements-sizing.js')
    unlock_js = _read_res('unlock-elements-sizing.js')
    # Guard: the scripts really do contain non-ASCII text
    assert not lock_js.isascii() and not unlock_js.isascii()
    assert lock_js in scripts
    assert unlock_js in scripts


def test_playwright_element_locking_scripts_read_as_utf8():
    from changedetectionio.content_fetchers.playwright import capture_full_page_async

    scripts = []
    page = SimpleNamespace(
        viewport_size={'width': 1280, 'height': 800},
        evaluate=_fake_evaluate(scripts),
        set_viewport_size=AsyncMock(),
        request_gc=AsyncMock(),
        screenshot=AsyncMock(return_value=b'screenshot'),
    )

    asyncio.run(capture_full_page_async(page, lock_viewport_elements=True))

    _assert_locking_scripts_evaluated(scripts)


def test_puppeteer_element_locking_scripts_read_as_utf8():
    from changedetectionio.content_fetchers.puppeteer import capture_full_page

    scripts = []
    page = SimpleNamespace(
        viewport={'width': 1280, 'height': 800},
        evaluate=_fake_evaluate(scripts),
        setViewport=AsyncMock(),
        screenshot=AsyncMock(return_value=b'screenshot'),
    )

    asyncio.run(capture_full_page(page, lock_viewport_elements=True))

    _assert_locking_scripts_evaluated(scripts)
