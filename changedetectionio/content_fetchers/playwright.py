import gc
import json
import os
from urllib.parse import urlparse

from loguru import logger

from changedetectionio.content_fetchers import SCREENSHOT_MAX_HEIGHT_DEFAULT, visualselector_xpath_selectors, \
    SCREENSHOT_SIZE_STITCH_THRESHOLD, SCREENSHOT_MAX_TOTAL_HEIGHT, XPATH_ELEMENT_JS, INSTOCK_DATA_JS, FAVICON_FETCHER_JS
from changedetectionio.content_fetchers.base import Fetcher, manage_user_agent
from changedetectionio.content_fetchers.exceptions import PageUnloadable, Non200ErrorCodeReceived, EmptyReply, ScreenshotUnavailable, \
    BrowserStepsStepException


async def capture_full_page_async(page, screenshot_format='JPEG', watch_uuid=None, lock_viewport_elements=False):
    import os
    import time

    start = time.time()
    watch_info = f"[{watch_uuid}] " if watch_uuid else ""

    setup_start = time.time()
    page_height = await page.evaluate("document.documentElement.scrollHeight")
    page_width = await page.evaluate("document.documentElement.scrollWidth")
    original_viewport = page.viewport_size
    dimensions_time = time.time() - setup_start

    logger.debug(f"{watch_info}Playwright viewport size {page.viewport_size} page height {page_height} page width {page_width} (got dimensions in {dimensions_time:.2f}s)")

    # Use an approach similar to puppeteer: set a larger viewport and take screenshots in chunks
    step_size = SCREENSHOT_SIZE_STITCH_THRESHOLD # Size that won't cause GPU to overflow
    screenshot_chunks = []
    y = 0
    elements_locked = False

    # Only lock viewport elements if explicitly enabled (for image_ssim_diff processor)
    # This prevents headers/ads from resizing when viewport changes
    if lock_viewport_elements and page_height > page.viewport_size['height']:
        lock_start = time.time()
        lock_elements_js_path = os.path.join(os.path.dirname(__file__), 'res', 'lock-elements-sizing.js')
        with open(lock_elements_js_path, 'r') as f:
            lock_elements_js = f.read()
        await page.evaluate(lock_elements_js)
        elements_locked = True
        lock_time = time.time() - lock_start
        logger.debug(f"{watch_info}Viewport element locking enabled (took {lock_time:.2f}s)")

    if page_height > page.viewport_size['height']:
        if page_height < step_size:
            step_size = page_height # Incase page is bigger than default viewport but smaller than proposed step size
        viewport_start = time.time()
        logger.debug(f"{watch_info}Setting bigger viewport to step through large page width W{page.viewport_size['width']}xH{step_size} because page_height > viewport_size")
        # Set viewport to a larger size to capture more content at once
        await page.set_viewport_size({'width': page.viewport_size['width'], 'height': step_size})
        viewport_time = time.time() - viewport_start
        logger.debug(f"{watch_info}Viewport changed to {page.viewport_size['width']}x{step_size} (took {viewport_time:.2f}s)")

    # Capture screenshots in chunks up to the max total height
    capture_start = time.time()
    chunk_times = []
    # Use PNG for better quality (no compression artifacts), JPEG for smaller size
    screenshot_type = screenshot_format.lower() if screenshot_format else 'jpeg'
    # PNG should use quality 100, JPEG uses configurable quality
    screenshot_quality = 100 if screenshot_type == 'png' else int(os.getenv("SCREENSHOT_QUALITY", 72))

    while y < min(page_height, SCREENSHOT_MAX_TOTAL_HEIGHT):
        # Only scroll if not at the top (y > 0)
        if y > 0:
            await page.evaluate(f"window.scrollTo(0, {y})")

        # Request GC only before screenshot (not 3x per chunk)
        await page.request_gc()

        screenshot_kwargs = {
            'type': screenshot_type,
            'full_page': False
        }
        # Only pass quality parameter for jpeg (PNG doesn't support it in Playwright)
        if screenshot_type == 'jpeg':
            screenshot_kwargs['quality'] = screenshot_quality

        chunk_start = time.time()
        screenshot_chunks.append(await page.screenshot(**screenshot_kwargs))
        chunk_time = time.time() - chunk_start
        chunk_times.append(chunk_time)
        logger.debug(f"{watch_info}Chunk {len(screenshot_chunks)} captured in {chunk_time:.2f}s")
        y += step_size

    # Restore original viewport size
    await page.set_viewport_size({'width': original_viewport['width'], 'height': original_viewport['height']})

    # Unlock element dimensions if they were locked
    if elements_locked:
        unlock_elements_js_path = os.path.join(os.path.dirname(__file__), 'res', 'unlock-elements-sizing.js')
        with open(unlock_elements_js_path, 'r') as f:
            unlock_elements_js = f.read()
        await page.evaluate(unlock_elements_js)
        logger.debug(f"{watch_info}Element dimensions unlocked after screenshot capture")

    capture_time = time.time() - capture_start
    total_capture_time = sum(chunk_times)
    logger.debug(f"{watch_info}All {len(screenshot_chunks)} chunks captured in {capture_time:.2f}s (total chunk time: {total_capture_time:.2f}s)")

    # If we have multiple chunks, stitch them together
    if len(screenshot_chunks) > 1:
        stitch_start = time.time()
        logger.debug(f"{watch_info}Starting stitching of {len(screenshot_chunks)} chunks")

        # Always use spawn subprocess for ANY stitching (2+ chunks)
        # PIL allocates at C level and Python GC never releases it - subprocess exit forces OS to reclaim
        # Trade-off: 35MB resource_tracker vs 500MB+ PIL leak in main process
        from changedetectionio.content_fetchers.screenshot_handler import stitch_images_worker_raw_bytes
        import multiprocessing
        import struct

        ctx = multiprocessing.get_context('spawn')
        parent_conn, child_conn = ctx.Pipe()
        p = ctx.Process(target=stitch_images_worker_raw_bytes, args=(child_conn, page_height, SCREENSHOT_MAX_TOTAL_HEIGHT))
        p.start()

        # Send via raw bytes (no pickle)
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
            f"{watch_info}Screenshot complete - Page height: {page_height}px, Capture height: {SCREENSHOT_MAX_TOTAL_HEIGHT}px | "
            f"Setup: {setup_time:.2f}s, Capture: {capture_time:.2f}s, Stitching: {stitch_time:.2f}s, Total: {total_time:.2f}s")
        return screenshot

    total_time = time.time() - start
    setup_time = total_time - capture_time
    logger.debug(
        f"{watch_info}Screenshot complete - Page height: {page_height}px, Capture height: {SCREENSHOT_MAX_TOTAL_HEIGHT}px | "
        f"Setup: {setup_time:.2f}s, Single chunk: {capture_time:.2f}s, Total: {total_time:.2f}s")

    return screenshot_chunks[0]

class fetcher(Fetcher):
    fetcher_description = "Playwright {}/Javascript".format(
        os.getenv("PLAYWRIGHT_BROWSER_TYPE", 'chromium').capitalize()
    )
    if os.getenv("PLAYWRIGHT_DRIVER_URL"):
        fetcher_description += " via '{}'".format(os.getenv("PLAYWRIGHT_DRIVER_URL"))

    browser_type = ''
    command_executor = ''

    # Configs for Proxy setup
    # In the ENV vars, is prefixed with "playwright_proxy_", so it is for example "playwright_proxy_server"
    playwright_proxy_settings_mappings = ['bypass', 'server', 'username', 'password']

    proxy = None

    # Capability flags
    supports_browser_steps = True
    supports_screenshots = True
    supports_xpath_element_data = True

    @classmethod
    def get_status_icon_data(cls):
        """Return Chrome browser icon data for Playwright fetcher."""
        return {
            'filename': 'google-chrome-icon.png',
            'alt': 'Using a Chrome browser',
            'title': 'Using a Chrome browser'
        }

    def __init__(self, proxy_override=None, custom_browser_connection_url=None, **kwargs):
        super().__init__(**kwargs)

        self.browser_type = os.getenv("PLAYWRIGHT_BROWSER_TYPE", 'chromium').strip('"')

        if custom_browser_connection_url:
            self.browser_connection_is_custom = True
            self.browser_connection_url = custom_browser_connection_url
        else:
            # Fallback to fetching from system
            # .strip('"') is going to save someone a lot of time when they accidently wrap the env value
            self.browser_connection_url = os.getenv("PLAYWRIGHT_DRIVER_URL", 'ws://playwright-chrome:3000').strip('"')

        # If any proxy settings are enabled, then we should setup the proxy object
        proxy_args = {}
        for k in self.playwright_proxy_settings_mappings:
            v = os.getenv('playwright_proxy_' + k, False)
            if v:
                proxy_args[k] = v.strip('"')

        if proxy_args:
            self.proxy = proxy_args

        # allow per-watch proxy selection override
        if proxy_override:
            self.proxy = {'server': proxy_override}

        if self.proxy:
            # Playwright needs separate username and password values
            parsed = urlparse(self.proxy.get('server'))
            if parsed.username:
                self.proxy['username'] = parsed.username
                self.proxy['password'] = parsed.password

    async def screenshot_step(self, step_n=''):
        super().screenshot_step(step_n=step_n)
        watch_uuid = getattr(self, 'watch_uuid', None)
        screenshot = await capture_full_page_async(page=self.page, screenshot_format=self.screenshot_format, watch_uuid=watch_uuid, lock_viewport_elements=self.lock_viewport_elements)

        # Request GC immediately after screenshot to free memory
        # Screenshots can be large and browser steps take many of them
        await self.page.request_gc()

        if self.browser_steps_screenshot_path is not None:
            destination = os.path.join(self.browser_steps_screenshot_path, 'step_{}.jpeg'.format(step_n))
            logger.debug(f"Saving step screenshot to {destination}")
            with open(destination, 'wb') as f:
                f.write(screenshot)
            # Clear local reference to allow screenshot bytes to be collected
            del screenshot
            gc.collect()

    async def save_step_html(self, step_n):
        super().save_step_html(step_n=step_n)
        content = await self.page.content()

        # Request GC after getting page content
        await self.page.request_gc()

        destination = os.path.join(self.browser_steps_screenshot_path, 'step_{}.html'.format(step_n))
        logger.debug(f"Saving step HTML to {destination}")
        with open(destination, 'w', encoding='utf-8') as f:
            f.write(content)
        # Clear local reference
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
        self.watch_uuid = watch_uuid  # Store for use in screenshot_step
        response = None

        async with async_playwright() as p:
            browser_type = getattr(p, self.browser_type)

            # Seemed to cause a connection Exception even tho I can see it connect
            # self.browser = browser_type.connect(self.command_executor, timeout=timeout*1000)
            # 60,000 connection timeout only
            browser = await browser_type.connect_over_cdp(self.browser_connection_url, timeout=60000)

            # SOCKS5 with authentication is not supported (yet)
            # https://github.com/microsoft/playwright/issues/10567

            # Set user agent to prevent Cloudflare from blocking the browser
            # Use the default one configured in the App.py model that's passed from fetch_site_status.py
            context = await browser.new_context(
                accept_downloads=False,  # Should never be needed
                bypass_csp=True,  # This is needed to enable JavaScript execution on GitHub and others
                extra_http_headers=request_headers,
                ignore_https_errors=True,
                proxy=self.proxy,
                service_workers=os.getenv('PLAYWRIGHT_SERVICE_WORKERS', 'allow'), # Should be `allow` or `block` - sites like YouTube can transmit large amounts of data via Service Workers
                user_agent=manage_user_agent(headers=request_headers),
            )

            self.page = await context.new_page()

            # Listen for all console events and handle errors
            self.page.on("console", lambda msg: logger.debug(f"Playwright console: Watch URL: {url} {msg.type}: {msg.text} {msg.args}"))

            # Re-use as much code from browser steps as possible so its the same
            from changedetectionio.blueprint.browser_steps.browser_steps import steppable_browser_interface
            browsersteps_interface = steppable_browser_interface(start_url=url)
            browsersteps_interface.page = self.page

            response = await browsersteps_interface.action_goto_url(value=url)

            if response is None:
                await context.close()
                await browser.close()
                logger.debug("Content Fetcher > Response object from the browser communication was none")
                raise EmptyReply(url=url, status_code=None)

            # In async_playwright, all_headers() returns a coroutine
            try:
                self.headers = await response.all_headers()
            except TypeError:
                # Fallback for sync version
                self.headers = response.all_headers()

            try:
                if self.webdriver_js_execute_code is not None and len(self.webdriver_js_execute_code):
                    await browsersteps_interface.action_execute_js(value=self.webdriver_js_execute_code, selector=None)
            except playwright._impl._errors.TimeoutError as e:
                await context.close()
                await browser.close()
                # This can be ok, we will try to grab what we could retrieve
                pass
            except Exception as e:
                logger.debug(f"Content Fetcher > Other exception when executing custom JS code {str(e)}")
                await context.close()
                await browser.close()
                raise PageUnloadable(url=url, status_code=None, message=str(e))

            extra_wait = int(os.getenv("WEBDRIVER_DELAY_BEFORE_CONTENT_READY", 5)) + self.render_extract_delay
            await self.page.wait_for_timeout(extra_wait * 1000)

            try:
                self.status_code = response.status
            except Exception as e:
                # https://github.com/dgtlmoon/changedetection.io/discussions/2122#discussioncomment-8241962
                logger.critical(f"Response from the browser/Playwright did not have a status_code! Response follows.")
                logger.critical(response)
                await context.close()
                await browser.close()
                raise PageUnloadable(url=url, status_code=None, message=str(e))

            if fetch_favicon:
                try:
                    self.favicon_blob = await self.page.evaluate(FAVICON_FETCHER_JS)
                    await self.page.request_gc()
                except Exception as e:
                    logger.error(f"Error fetching FavIcon info {str(e)}, continuing.")

            if self.status_code != 200 and not ignore_status_codes:
                screenshot = await capture_full_page_async(self.page, screenshot_format=self.screenshot_format, watch_uuid=watch_uuid, lock_viewport_elements=self.lock_viewport_elements)
                # Cleanup before raising to prevent memory leak
                await self.page.close()
                await context.close()
                await browser.close()
                # Force garbage collection to release Playwright resources immediately
                gc.collect()
                raise Non200ErrorCodeReceived(url=url, status_code=self.status_code, screenshot=screenshot)

            if not empty_pages_are_a_change and len((await self.page.content()).strip()) == 0:
                logger.debug("Content Fetcher > Content was empty, empty_pages_are_a_change = False")
                await context.close()
                await browser.close()
                raise EmptyReply(url=url, status_code=response.status)

            # Wrap remaining operations in try/finally to ensure cleanup
            try:
                # Run Browser Steps here
                if self.browser_steps_get_valid_steps():
                    try:
                        await self.iterate_browser_steps(start_url=url)
                    except BrowserStepsStepException:
                        try:
                            await context.close()
                            await browser.close()
                        except Exception as e:
                            # Fine, could be messy situation
                            pass
                        raise

                    await self.page.wait_for_timeout(extra_wait * 1000)

                now = time.time()
                # So we can find an element on the page where its selector was entered manually (maybe not xPath etc)
                if current_include_filters is not None:
                    await self.page.evaluate("var include_filters={}".format(json.dumps(current_include_filters)))
                else:
                    await self.page.evaluate("var include_filters=''")
                await self.page.request_gc()

                # request_gc before and after evaluate to free up memory
                # @todo browsersteps etc
                MAX_TOTAL_HEIGHT = int(os.getenv("SCREENSHOT_MAX_HEIGHT", SCREENSHOT_MAX_HEIGHT_DEFAULT))
                self.xpath_data = await self.page.evaluate(XPATH_ELEMENT_JS, {
                    "visualselector_xpath_selectors": visualselector_xpath_selectors,
                    "max_height": MAX_TOTAL_HEIGHT
                })
                await self.page.request_gc()

                self.instock_data = await self.page.evaluate(INSTOCK_DATA_JS)
                await self.page.request_gc()

                self.content = await self.page.content()
                await self.page.request_gc()
                logger.debug(f"Scrape xPath element data in browser done in {time.time() - now:.2f}s")


                # Bug 3 in Playwright screenshot handling
                # Some bug where it gives the wrong screenshot size, but making a request with the clip set first seems to solve it
                # JPEG is better here because the screenshots can be very very large

                # Screenshots also travel via the ws:// (websocket) meaning that the binary data is base64 encoded
                # which will significantly increase the IO size between the server and client, it's recommended to use the lowest
                # acceptable screenshot quality here
                # The actual screenshot - this always base64 and needs decoding! horrible! huge CPU usage
                self.screenshot = await capture_full_page_async(page=self.page, screenshot_format=self.screenshot_format, watch_uuid=watch_uuid, lock_viewport_elements=self.lock_viewport_elements)

                # Force aggressive memory cleanup - screenshots are large and base64 decode creates temporary buffers
                await self.page.request_gc()
                gc.collect()

            except ScreenshotUnavailable:
                # Re-raise screenshot unavailable exceptions
                raise ScreenshotUnavailable(url=url, status_code=self.status_code)
            except BrowserStepsStepException:
                raise
            except Exception:
                # It's likely the screenshot was too long/big and something crashed
                raise
            finally:
                # Request garbage collection one more time before closing
                try:
                    await self.page.request_gc()
                except:
                    pass
                
                # Clean up resources properly
                try:
                    await self.page.request_gc()
                except:
                    pass

                try:
                    await self.page.close()
                except:
                    pass
                self.page = None

                try:
                    await context.close()
                except:
                    pass
                context = None

                try:
                    await browser.close()
                except:
                    pass
                browser = None

                # Force Python GC to release Playwright resources immediately
                # Playwright objects can have circular references that delay cleanup
                gc.collect()


# Plugin registration for built-in fetcher
class PlaywrightFetcherPlugin:
    """Plugin class that registers the Playwright fetcher as a built-in plugin."""

    def register_content_fetcher(self):
        """Register the Playwright fetcher"""
        return ('html_webdriver', fetcher)


# Create module-level instance for plugin registration
playwright_plugin = PlaywrightFetcherPlugin()



