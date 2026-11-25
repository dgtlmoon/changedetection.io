#!/usr/bin/env python3
"""Opens a page in a real browser for a test and hands it over, see run_in_browser()."""

import asyncio
import os
import re

import pytest
from flask import url_for

VIEWPORT = {'width': 1280, 'height': 900}

# Where the browser finds the application, set by the running_app fixture
APP_URL = None


def site_url(endpoint, **values):
    """Address of a page of the running application (the `running_app` fixture) as the browser sees it"""
    assert APP_URL, "Use the running_app fixture"
    return APP_URL + url_for(endpoint, _external=False, **values)


async def screenshot(page, name, selector=None, room_below=0):
    """Saved only when UI_TEST_SCREENSHOT_DIR is set (CI keeps them as an artifact). With a selector, that
    element with some room around it (and `room_below` for a list that drops down from it)."""
    directory = os.getenv('UI_TEST_SCREENSHOT_DIR')
    if not directory:
        return
    os.makedirs(directory, exist_ok=True)
    options = {'path': os.path.join(directory, re.sub(r'[^\w.-]', '_', name) + '.png')}
    if selector:
        box = await (await page.querySelector(selector)).boundingBox()
        options['clip'] = {'x': max(box['x'] - 20, 0), 'y': max(box['y'] - 20, 0),
                           'width': box['width'] + 40, 'height': box['height'] + 40 + room_below}
    await page.screenshot(**options)


async def wait_until(page, js_condition, what, timeout=8):
    """Waits for `js_condition` (a JavaScript expression) to be true in the page. Asked again and again from here:
    pyppeteer's own waitForFunction() does not wait with this browser."""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        try:
            if await page.evaluate(f"() => !!({js_condition})"):
                return
        except Exception:
            # The page is between two documents
            pass
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError(f"Waited {timeout}s for: {what}")
        await asyncio.sleep(0.05)


async def leave_page(page, action, what):
    """Something that leaves the page (`await action()`: a click on Save, Enter in a form), done when the page
    it lands on has loaded."""
    await page.evaluate("() => { window.pageBeforeLeaving = true; }")
    await action()
    await wait_until(page, "!window.pageBeforeLeaving && document.readyState === 'complete'", f"the page after {what}", timeout=20)


async def click_and_wait_for_new_page(page, selector):
    await leave_page(page, lambda: page.click(selector), f"clicking {selector}")


async def press_enter_and_wait_for_new_page(page):
    await leave_page(page, lambda: page.keyboard.press('Enter'), "pressing Enter")


def run_in_browser(steps, name, dark_mode=False):
    """Runs `await steps(page)` with a new page of the browser.

    When a step fails, what the browser was showing is saved as "FAILED-<name>.png" (UI_TEST_SCREENSHOT_DIR).
    """
    browser_url = os.getenv('PLAYWRIGHT_DRIVER_URL')
    if not browser_url:
        pytest.skip("Needs a browser to drive, set PLAYWRIGHT_DRIVER_URL (ws://sockpuppetbrowser:3000)")

    async def run():
        from pyppeteer import Pyppeteer

        browser = await Pyppeteer().connect(browserWSEndpoint=browser_url)
        try:
            page = await browser.newPage()
            await page.setViewport(VIEWPORT)
            page.setDefaultNavigationTimeout(20000)
            if dark_mode:
                # The cookie of the theme switch in the menu
                await page.setCookie({'name': 'css_dark_mode', 'value': 'true', 'url': site_url('watchlist.index')})
            try:
                await steps(page)
            except BaseException:
                await screenshot(page, f"FAILED-{name}")
                raise
        finally:
            await browser.close()

    asyncio.run(run())
