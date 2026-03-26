"""
Playwright-based content fetchers.

Submodules:
  cdp     — connect to a remote browser via Chrome DevTools Protocol (CDP/WebSocket)
  chrome  — launch a local Chromium browser
  firefox — launch a local Firefox browser
  webkit  — launch a local WebKit (Safari-engine) browser
"""

import asyncio
import gc
import json
import os
import re
from urllib.parse import urlparse

from loguru import logger

from changedetectionio.content_fetchers import (
    SCREENSHOT_MAX_HEIGHT_DEFAULT,
    SCREENSHOT_MAX_TOTAL_HEIGHT,
    SCREENSHOT_SIZE_STITCH_THRESHOLD,
    FAVICON_FETCHER_JS,
    INSTOCK_DATA_JS,
    XPATH_ELEMENT_JS,
    visualselector_xpath_selectors,
)
from changedetectionio.content_fetchers.base import Fetcher, manage_user_agent
from changedetectionio.content_fetchers.exceptions import (
    BrowserStepsStepException,
    EmptyReply,
    Non200ErrorCodeReceived,
    PageUnloadable,
    ScreenshotUnavailable,
)


async def capture_full_page_async(page, screenshot_format='JPEG', watch_uuid=None, lock_viewport_elements=False):
    import time

    start = time.time()
    watch_info = f"[{watch_uuid}] " if watch_uuid else ""

    setup_start = time.time()
    page_height = await page.evaluate("document.documentElement.scrollHeight")
    page_width = await page.evaluate("document.documentElement.scrollWidth")
    original_viewport = page.viewport_size
    dimensions_time = time.time() - setup_start

    logger.debug(f"{watch_info}Playwright viewport size {page.viewport_size} page height {page_height} page width {page_width} (got dimensions in {dimensions_time:.2f}s)")

    step_size = SCREENSHOT_SIZE_STITCH_THRESHOLD
    screenshot_chunks = []
    y = 0
    elements_locked = False

    if lock_viewport_elements and page_height > page.viewport_size['height']:
        lock_start = time.time()
        lock_elements_js_path = os.path.join(os.path.dirname(__file__), '..', 'res', 'lock-elements-sizing.js')
        with open(lock_elements_js_path, 'r') as f:
            lock_elements_js = f.read()
        await page.evaluate(lock_elements_js)
        elements_locked = True
        logger.debug(f"{watch_info}Viewport element locking enabled (took {time.time() - lock_start:.2f}s)")

    if page_height > page.viewport_size['height']:
        if page_height < step_size:
            step_size = page_height
        await page.set_viewport_size({'width': page.viewport_size['width'], 'height': step_size})

    capture_start = time.time()
    chunk_times = []
    screenshot_type = screenshot_format.lower() if screenshot_format else 'jpeg'
    screenshot_quality = 100 if screenshot_type == 'png' else int(os.getenv("SCREENSHOT_QUALITY", 72))

    while y < min(page_height, SCREENSHOT_MAX_TOTAL_HEIGHT):
        if y > 0:
            await page.evaluate(f"window.scrollTo(0, {y})")

        await _safe_request_gc(page)

        screenshot_kwargs = {'type': screenshot_type, 'full_page': False}
        if screenshot_type == 'jpeg':
            screenshot_kwargs['quality'] = screenshot_quality

        chunk_start = time.time()
        screenshot_chunks.append(await page.screenshot(**screenshot_kwargs))
        chunk_time = time.time() - chunk_start
        chunk_times.append(chunk_time)
        logger.debug(f"{watch_info}Chunk {len(screenshot_chunks)} captured in {chunk_time:.2f}s")
        y += step_size

    await page.set_viewport_size({'width': original_viewport['width'], 'height': original_viewport['height']})

    if elements_locked:
        unlock_elements_js_path = os.path.join(os.path.dirname(__file__), '..', 'res', 'unlock-elements-sizing.js')
        with open(unlock_elements_js_path, 'r') as f:
            unlock_elements_js = f.read()
        await page.evaluate(unlock_elements_js)

    capture_time = time.time() - capture_start

    if len(screenshot_chunks) > 1:
        stitch_start = time.time()
        from changedetectionio.content_fetchers.screenshot_handler import stitch_images_worker_raw_bytes
        import multiprocessing
        import struct

        ctx = multiprocessing.get_context('spawn')
        parent_conn, child_conn = ctx.Pipe()
        p = ctx.Process(target=stitch_images_worker_raw_bytes, args=(child_conn, page_height, SCREENSHOT_MAX_TOTAL_HEIGHT))
        p.start()

        parent_conn.send_bytes(struct.pack('I', len(screenshot_chunks)))
        for chunk in screenshot_chunks:
            parent_conn.send_bytes(chunk)

        screenshot = parent_conn.recv_bytes()
        p.join()
        parent_conn.close()
        child_conn.close()
        del p, parent_conn, child_conn

        stitch_time = time.time() - stitch_start
        total_time = time.time() - start
        setup_time = total_time - capture_time - stitch_time
        logger.debug(
            f"{watch_info}Screenshot complete - Page height: {page_height}px | "
            f"Setup: {setup_time:.2f}s, Capture: {capture_time:.2f}s, Stitching: {stitch_time:.2f}s, Total: {total_time:.2f}s")
        return screenshot

    total_time = time.time() - start
    logger.debug(
        f"{watch_info}Screenshot complete - Page height: {page_height}px | "
        f"Setup: {total_time - capture_time:.2f}s, Single chunk: {capture_time:.2f}s, Total: {total_time:.2f}s")
    return screenshot_chunks[0]


async def _safe_request_gc(page):
    """Request browser GC — Chromium-specific, silently ignored on Firefox/WebKit."""
    try:
        await page.request_gc()
    except Exception:
        pass


class PlaywrightBaseFetcher(Fetcher):
    """
    Shared base for all Playwright fetchers.

    Subclasses implement ``_connect_browser(playwright_instance)`` to return a
    connected-or-launched browser object.  Everything else — context creation,
    page interaction, screenshot capture, browser-steps execution — lives here.
    """

    playwright_proxy_settings_mappings = ['bypass', 'server', 'username', 'password']

    proxy = None

    # Capability flags
    supports_browser_steps = True
    supports_screenshots = True
    supports_xpath_element_data = True

    status_icon = {'filename': 'google-chrome-icon.png', 'alt': 'Using a Chrome browser', 'title': 'Using a Chrome browser'}

    def __init__(self, proxy_override=None, custom_browser_connection_url=None, **kwargs):
        super().__init__(**kwargs)

        # Subclasses may use this (e.g. CDP); others ignore it
        self._custom_browser_connection_url = custom_browser_connection_url

        proxy_args = {}
        for k in self.playwright_proxy_settings_mappings:
            v = os.getenv('playwright_proxy_' + k, False)
            if v:
                proxy_args[k] = v.strip('"')

        if proxy_args:
            self.proxy = proxy_args

        if proxy_override:
            self.proxy = {'server': proxy_override}

        if self.proxy:
            parsed = urlparse(self.proxy.get('server', ''))
            if parsed.username:
                self.proxy['username'] = parsed.username
                self.proxy['password'] = parsed.password

    def disk_cleanup_after_fetch(self):
        """Delete browser-step screenshots written during this fetch."""
        self.delete_browser_steps_screenshots()

    async def _connect_browser(self, playwright_instance):
        """Return an open browser object.  Must be overridden by each subclass."""
        raise NotImplementedError(f"{type(self).__name__} must implement _connect_browser()")

    async def screenshot_step(self, step_n=''):
        super().screenshot_step(step_n=step_n)
        watch_uuid = getattr(self, 'watch_uuid', None)
        screenshot = await capture_full_page_async(
            page=self.page,
            screenshot_format=self.screenshot_format,
            watch_uuid=watch_uuid,
            lock_viewport_elements=self.lock_viewport_elements,
        )
        await _safe_request_gc(self.page)

        if self.browser_steps_screenshot_path is not None:
            destination = os.path.join(self.browser_steps_screenshot_path, 'step_{}.jpeg'.format(step_n))
            logger.debug(f"Saving step screenshot to {destination}")
            with open(destination, 'wb') as f:
                f.write(screenshot)
            del screenshot
            gc.collect()

    async def save_step_html(self, step_n):
        super().save_step_html(step_n=step_n)
        content = await self.page.content()
        await _safe_request_gc(self.page)

        destination = os.path.join(self.browser_steps_screenshot_path, 'step_{}.html'.format(step_n))
        logger.debug(f"Saving step HTML to {destination}")
        with open(destination, 'w', encoding='utf-8') as f:
            f.write(content)
        del content
        gc.collect()

    async def run(self,
                  fetch_favicon=True,
                  current_include_filters=None,
                  empty_pages_are_a_change=False,
                  ignore_status_codes=False,
                  is_binary=False,
                  request_body=None,
                  request_headers=None,
                  request_method=None,
                  screenshot_format=None,
                  timeout=None,
                  url=None,
                  watch_uuid=None,
                  ):
        from playwright.async_api import async_playwright
        import playwright._impl._errors
        import time

        self.delete_browser_steps_screenshots()
        self.watch_uuid = watch_uuid
        response = None

        async with async_playwright() as p:
            browser = await self._connect_browser(p)

            ua = manage_user_agent(headers=request_headers) or self.profile_user_agent or None

            context_kwargs = dict(
                accept_downloads=False,
                bypass_csp=True,
                extra_http_headers=request_headers,
                ignore_https_errors=self.ignore_https_errors,
                proxy=self.proxy,
                service_workers=self.service_workers,
                user_agent=ua,
                viewport={'width': self.viewport_width, 'height': self.viewport_height},
            )
            if self.locale:
                context_kwargs['locale'] = self.locale

            context = await browser.new_context(**context_kwargs)

            if self.block_images:
                await context.route(
                    re.compile(r'\.(png|jpe?g|gif|svg|ico|webp|avif|bmp)(\?.*)?$', re.IGNORECASE),
                    lambda route: route.abort()
                )
            if self.block_fonts:
                await context.route(
                    re.compile(r'\.(woff2?|ttf|otf|eot)(\?.*)?$', re.IGNORECASE),
                    lambda route: route.abort()
                )

            self.page = await context.new_page()
            self.page.on("console", lambda msg: logger.debug(f"Playwright console: {url} {msg.type}: {msg.text}"))

            from changedetectionio.browser_steps.browser_steps import steppable_browser_interface
            browsersteps_interface = steppable_browser_interface(start_url=url)
            browsersteps_interface.page = self.page

            response = await browsersteps_interface.action_goto_url(value=url)

            if response is None:
                await context.close()
                await browser.close()
                raise EmptyReply(url=url, status_code=None)

            try:
                self.headers = await response.all_headers()
            except TypeError:
                self.headers = response.all_headers()

            try:
                if self.webdriver_js_execute_code is not None and len(self.webdriver_js_execute_code):
                    await browsersteps_interface.action_execute_js(value=self.webdriver_js_execute_code, selector=None)
            except playwright._impl._errors.TimeoutError:
                await context.close()
                await browser.close()
                pass
            except Exception as e:
                await context.close()
                await browser.close()
                raise PageUnloadable(url=url, status_code=None, message=str(e))

            extra_wait = self.extra_delay + self.render_extract_delay
            await self.page.wait_for_timeout(extra_wait * 1000)

            try:
                self.status_code = response.status
            except Exception as e:
                await context.close()
                await browser.close()
                raise PageUnloadable(url=url, status_code=None, message=str(e))

            if fetch_favicon:
                try:
                    self.favicon_blob = await self.page.evaluate(FAVICON_FETCHER_JS)
                    await _safe_request_gc(self.page)
                except Exception as e:
                    logger.error(f"Error fetching favicon: {e}")

            if self.status_code != 200 and not ignore_status_codes:
                screenshot = await capture_full_page_async(self.page, screenshot_format=self.screenshot_format, watch_uuid=watch_uuid, lock_viewport_elements=self.lock_viewport_elements)
                raise Non200ErrorCodeReceived(url=url, status_code=self.status_code, screenshot=screenshot)

            if not empty_pages_are_a_change and len((await self.page.content()).strip()) == 0:
                await context.close()
                await browser.close()
                raise EmptyReply(url=url, status_code=response.status)

            try:
                if self.browser_steps:
                    try:
                        await self.iterate_browser_steps(start_url=url)
                    except BrowserStepsStepException:
                        raise
                    await self.page.wait_for_timeout(extra_wait * 1000)

                now = time.time()
                if current_include_filters is not None:
                    await self.page.evaluate("var include_filters={}".format(json.dumps(current_include_filters)))
                else:
                    await self.page.evaluate("var include_filters=''")
                await _safe_request_gc(self.page)

                MAX_TOTAL_HEIGHT = int(os.getenv("SCREENSHOT_MAX_HEIGHT", SCREENSHOT_MAX_HEIGHT_DEFAULT))
                self.xpath_data = await self.page.evaluate(XPATH_ELEMENT_JS, {
                    "visualselector_xpath_selectors": visualselector_xpath_selectors,
                    "max_height": MAX_TOTAL_HEIGHT
                })
                await _safe_request_gc(self.page)

                self.instock_data = await self.page.evaluate(INSTOCK_DATA_JS)
                await _safe_request_gc(self.page)

                self.content = await self.page.content()
                await _safe_request_gc(self.page)
                logger.debug(f"Scrape xPath element data done in {time.time() - now:.2f}s")

                self.screenshot = await capture_full_page_async(
                    page=self.page,
                    screenshot_format=self.screenshot_format,
                    watch_uuid=watch_uuid,
                    lock_viewport_elements=self.lock_viewport_elements,
                )
                await _safe_request_gc(self.page)
                gc.collect()

            except ScreenshotUnavailable:
                raise ScreenshotUnavailable(url=url, status_code=self.status_code)

            finally:
                for obj, name, close_coro in [
                    (self.page if hasattr(self, 'page') and self.page else None, 'page', lambda: self.page.close() if self.page else asyncio.sleep(0)),
                    (context, 'context', lambda: context.close() if context else asyncio.sleep(0)),
                    (browser, 'browser', lambda: browser.close() if browser else asyncio.sleep(0)),
                ]:
                    try:
                        await asyncio.wait_for(close_coro(), timeout=5.0)
                    except asyncio.TimeoutError:
                        logger.warning(f"Timed out closing {name} for {url}")
                    except Exception as e:
                        logger.warning(f"Error closing {name} for {url}: {e}")

                self.page = None
                context = None
                browser = None
                gc.collect()
