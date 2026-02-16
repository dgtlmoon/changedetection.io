import asyncio
import gc
import json
import os
import websockets.exceptions
from urllib.parse import urlparse

from loguru import logger

from changedetectionio.content_fetchers import SCREENSHOT_MAX_HEIGHT_DEFAULT, visualselector_xpath_selectors, \
    SCREENSHOT_SIZE_STITCH_THRESHOLD, SCREENSHOT_DEFAULT_QUALITY, XPATH_ELEMENT_JS, INSTOCK_DATA_JS, \
    SCREENSHOT_MAX_TOTAL_HEIGHT, FAVICON_FETCHER_JS
from changedetectionio.content_fetchers.base import Fetcher, manage_user_agent
from changedetectionio.content_fetchers.exceptions import PageUnloadable, Non200ErrorCodeReceived, EmptyReply, BrowserFetchTimedOut, \
    BrowserConnectError


# Bug 3 in Playwright screenshot handling
# Some bug where it gives the wrong screenshot size, but making a request with the clip set first seems to solve it

# Screenshots also travel via the ws:// (websocket) meaning that the binary data is base64 encoded
# which will significantly increase the IO size between the server and client, it's recommended to use the lowest
# acceptable screenshot quality here
async def capture_full_page(page, screenshot_format='JPEG', watch_uuid=None, lock_viewport_elements=False):
    import os
    import time

    start = time.time()
    watch_info = f"[{watch_uuid}] " if watch_uuid else ""

    setup_start = time.time()
    page_height = await page.evaluate("document.documentElement.scrollHeight")
    page_width = await page.evaluate("document.documentElement.scrollWidth")
    original_viewport = page.viewport
    dimensions_time = time.time() - setup_start

    logger.debug(f"{watch_info}Puppeteer viewport size {page.viewport} page height {page_height} page width {page_width} (got dimensions in {dimensions_time:.2f}s)")

    # Bug 3 in Playwright screenshot handling
    # Some bug where it gives the wrong screenshot size, but making a request with the clip set first seems to solve it
    # JPEG is better here because the screenshots can be very very large

    # Screenshots also travel via the ws:// (websocket) meaning that the binary data is base64 encoded
    # which will significantly increase the IO size between the server and client, it's recommended to use the lowest
    # acceptable screenshot quality here

    # Use PNG for better quality (no compression artifacts), JPEG for smaller size
    screenshot_type = screenshot_format.lower() if screenshot_format else 'jpeg'
    # PNG should use quality 100, JPEG uses configurable quality
    screenshot_quality = 100 if screenshot_type == 'png' else int(os.getenv("SCREENSHOT_QUALITY", 72))

    step_size = SCREENSHOT_SIZE_STITCH_THRESHOLD # Something that will not cause the GPU to overflow when taking the screenshot
    screenshot_chunks = []
    y = 0
    elements_locked = False

    # Only lock viewport elements if explicitly enabled (for image_ssim_diff processor)
    # This prevents headers/ads from resizing when viewport changes
    if lock_viewport_elements and page_height > page.viewport['height']:
        lock_start = time.time()
        lock_elements_js_path = os.path.join(os.path.dirname(__file__), 'res', 'lock-elements-sizing.js')
        file_read_start = time.time()
        with open(lock_elements_js_path, 'r') as f:
            lock_elements_js = f.read()
        file_read_time = time.time() - file_read_start

        evaluate_start = time.time()
        await page.evaluate(lock_elements_js)
        evaluate_time = time.time() - evaluate_start

        elements_locked = True
        lock_time = time.time() - lock_start
        logger.debug(f"{watch_info}Viewport element locking enabled - File read: {file_read_time:.3f}s, Browser evaluate: {evaluate_time:.2f}s, Total: {lock_time:.2f}s")

    if page_height > page.viewport['height']:
        if page_height < step_size:
            step_size = page_height # Incase page is bigger than default viewport but smaller than proposed step size
        viewport_start = time.time()
        await page.setViewport({'width': page.viewport['width'], 'height': step_size})
        viewport_time = time.time() - viewport_start
        logger.debug(f"{watch_info}Viewport changed to {page.viewport['width']}x{step_size} (took {viewport_time:.2f}s)")

    capture_start = time.time()
    chunk_times = []
    while y < min(page_height, SCREENSHOT_MAX_TOTAL_HEIGHT):
        # better than scrollTo incase they override it in the page
        await page.evaluate(
            """(y) => {
                document.documentElement.scrollTop = y;
                document.body.scrollTop = y;
            }""",
            y
        )

        screenshot_kwargs = {
            'type_': screenshot_type,
            'fullPage': False
        }
        # PNG doesn't support quality parameter in Puppeteer
        if screenshot_type == 'jpeg':
            screenshot_kwargs['quality'] = screenshot_quality

        chunk_start = time.time()
        screenshot_chunks.append(await page.screenshot(**screenshot_kwargs))
        chunk_time = time.time() - chunk_start
        chunk_times.append(chunk_time)
        logger.debug(f"{watch_info}Chunk {len(screenshot_chunks)} captured in {chunk_time:.2f}s")
        y += step_size

    await page.setViewport({'width': original_viewport['width'], 'height': original_viewport['height']})

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
    fetcher_description = "Puppeteer/direct {}/Javascript".format(
        os.getenv("PLAYWRIGHT_BROWSER_TYPE", 'chromium').capitalize()
    )
    if os.getenv("PLAYWRIGHT_DRIVER_URL"):
        fetcher_description += " via '{}'".format(os.getenv("PLAYWRIGHT_DRIVER_URL"))

    browser = None
    browser_type = ''
    command_executor = ''
    proxy = None

    # Capability flags
    supports_browser_steps = True
    supports_screenshots = True
    supports_xpath_element_data = True

    @classmethod
    def get_status_icon_data(cls):
        """Return Chrome browser icon data for Puppeteer fetcher."""
        return {
            'filename': 'google-chrome-icon.png',
            'alt': 'Using a Chrome browser',
            'title': 'Using a Chrome browser'
        }

    def __init__(self, proxy_override=None, custom_browser_connection_url=None, **kwargs):
        super().__init__(**kwargs)

        if custom_browser_connection_url:
            self.browser_connection_is_custom = True
            self.browser_connection_url = custom_browser_connection_url
        else:
            # Fallback to fetching from system
            # .strip('"') is going to save someone a lot of time when they accidently wrap the env value
            self.browser_connection_url = os.getenv("PLAYWRIGHT_DRIVER_URL", 'ws://playwright-chrome:3000').strip('"')

        # allow per-watch proxy selection override
        # @todo check global too?
        if proxy_override:
            # Playwright needs separate username and password values
            parsed = urlparse(proxy_override)
            if parsed:
                self.proxy = {'username': parsed.username, 'password': parsed.password}
                # Add the proxy server chrome start option, the username and password never gets added here
                # (It always goes in via await self.page.authenticate(self.proxy))

                # @todo filter some injection attack?
                # check scheme when no scheme
                proxy_url = parsed.scheme + "://" if parsed.scheme else 'http://'
                r = "?" if not '?' in self.browser_connection_url else '&'
                port = ":"+str(parsed.port) if parsed.port else ''
                q = "?"+parsed.query if parsed.query else ''
                proxy_url += f"{parsed.hostname}{port}{parsed.path}{q}"
                self.browser_connection_url += f"{r}--proxy-server={proxy_url}"

    async def quit(self, watch=None):
        watch_uuid = watch.get('uuid') if watch else 'unknown'

        # Close page
        try:
            if hasattr(self, 'page') and self.page:
                await asyncio.wait_for(self.page.close(), timeout=5.0)
                logger.debug(f"[{watch_uuid}] Page closed successfully")
        except asyncio.TimeoutError:
            logger.warning(f"[{watch_uuid}] Timed out closing page (5s)")
        except Exception as e:
            logger.warning(f"[{watch_uuid}] Error closing page: {e}")
        finally:
            self.page = None

        # Close browser connection
        try:
            if hasattr(self, 'browser') and self.browser:
                await asyncio.wait_for(self.browser.close(), timeout=5.0)
                logger.debug(f"[{watch_uuid}] Browser closed successfully")
        except asyncio.TimeoutError:
            logger.warning(f"[{watch_uuid}] Timed out closing browser (5s)")
        except Exception as e:
            logger.warning(f"[{watch_uuid}] Error closing browser: {e}")
        finally:
            self.browser = None

        logger.info(f"[{watch_uuid}] Cleanup puppeteer complete")

        # Force garbage collection to release resources
        gc.collect()

    async def fetch_page(self,
                         current_include_filters,
                         empty_pages_are_a_change,
                         fetch_favicon,
                         ignore_status_codes,
                         is_binary,
                         request_body,
                         request_headers,
                         request_method,
                         screenshot_format,
                         timeout,
                         url,
                         watch_uuid
                         ):
        import re
        self.delete_browser_steps_screenshots()

        n = int(os.getenv("WEBDRIVER_DELAY_BEFORE_CONTENT_READY", 12)) + self.render_extract_delay
        extra_wait = min(n, 15)

        logger.debug(f"Extra wait set to {extra_wait}s, requested was {n}s.")

        from pyppeteer import Pyppeteer
        pyppeteer_instance = Pyppeteer()

        # Connect directly using the specified browser_ws_endpoint
        # @todo timeout
        try:
            logger.debug(f"[{watch_uuid}] Connecting to browser at {self.browser_connection_url}")
            self.browser = await pyppeteer_instance.connect(browserWSEndpoint=self.browser_connection_url,
                                                            ignoreHTTPSErrors=True
                                                            )
            logger.debug(f"[{watch_uuid}] Browser connected successfully")
        except websockets.exceptions.InvalidStatusCode as e:
            raise BrowserConnectError(msg=f"Error while trying to connect the browser, Code {e.status_code} (check your access, whitelist IP, password etc)")
        except websockets.exceptions.InvalidURI:
            raise BrowserConnectError(msg=f"Error connecting to the browser, check your browser connection address (should be ws:// or wss://")
        except Exception as e:
            raise BrowserConnectError(msg=f"Error connecting to the browser - Exception '{str(e)}'")

        # more reliable is to just request a new page
        try:
            logger.debug(f"[{watch_uuid}] Creating new page")
            self.page = await self.browser.newPage()
            logger.debug(f"[{watch_uuid}] Page created successfully")
        except Exception as e:
            logger.error(f"[{watch_uuid}] Failed to create new page: {e}")
            # Browser is connected but page creation failed - must cleanup browser
            try:
                await asyncio.wait_for(self.browser.close(), timeout=3.0)
            except Exception as cleanup_error:
                logger.error(f"[{watch_uuid}] Failed to cleanup browser after page creation failure: {cleanup_error}")
            raise
        
        # Add console handler to capture console.log from favicon fetcher
        #self.page.on('console', lambda msg: logger.debug(f"Browser console [{msg.type}]: {msg.text}"))

        if '--window-size' in self.browser_connection_url:
            # Be sure the viewport is always the window-size, this is often not the same thing
            match = re.search(r'--window-size=(\d+),(\d+)', self.browser_connection_url)
            if match:
                logger.debug(f"Setting viewport to same as --window-size in browser connection URL {int(match.group(1))},{int(match.group(2))}")
                await self.page.setViewport({
                    "width": int(match.group(1)),
                    "height": int(match.group(2))
                })
                logger.debug(f"Puppeteer viewport size {self.page.viewport}")
        try:
            from pyppeteerstealth import inject_evasions_into_page
        except ImportError:
            logger.debug("pyppeteerstealth module not available, skipping")
            pass
        else:
            # I tried hooking events via self.page.on(Events.Page.DOMContentLoaded, inject_evasions_requiring_obj_to_page)
            # But I could never get it to fire reliably, so we just inject it straight after
            await inject_evasions_into_page(self.page)

        # This user agent is similar to what was used when tweaking the evasions in inject_evasions_into_page(..)
        user_agent = None
        if request_headers and request_headers.get('User-Agent'):
            # Request_headers should now be CaaseInsensitiveDict
            # Remove it so it's not sent again with headers after
            user_agent = request_headers.pop('User-Agent').strip()
            await self.page.setUserAgent(user_agent)

        if not user_agent:
            # Attempt to strip 'HeadlessChrome' etc
            await self.page.setUserAgent(manage_user_agent(headers=request_headers, current_ua=await self.page.evaluate('navigator.userAgent')))

        await self.page.setBypassCSP(True)
        if request_headers:
            await self.page.setExtraHTTPHeaders(request_headers)

        # SOCKS5 with authentication is not supported (yet)
        # https://github.com/microsoft/playwright/issues/10567
        self.page.setDefaultNavigationTimeout(0)
        await self.page.setCacheEnabled(True)
        if self.proxy and self.proxy.get('username'):
            # Setting Proxy-Authentication header is deprecated, and doing so can trigger header change errors from Puppeteer
            # https://github.com/puppeteer/puppeteer/issues/676 ?
            # https://help.brightdata.com/hc/en-us/articles/12632549957649-Proxy-Manager-How-to-Guides#h_01HAKWR4Q0AFS8RZTNYWRDFJC2
            # https://cri.dev/posts/2020-03-30-How-to-solve-Puppeteer-Chrome-Error-ERR_INVALID_ARGUMENT/
            await self.page.authenticate(self.proxy)

        # Re-use as much code from browser steps as possible so its the same
        # from changedetectionio.blueprint.browser_steps.browser_steps import steppable_browser_interface

        # not yet used here, we fallback to playwright when browsersteps is required
        #            browsersteps_interface = steppable_browser_interface()
        #            browsersteps_interface.page = self.page

        # Enable Network domain to detect when first bytes arrive
        await self.page._client.send('Network.enable')

        # Now set up the frame navigation handlers
        async def handle_frame_navigation(event=None):
            # Wait n seconds after the frameStartedLoading, not from any frameStartedLoading/frameStartedNavigating
            logger.debug(f"Frame navigated: {event}")
            w = extra_wait - 2 if extra_wait > 4 else 2
            logger.debug(f"Waiting {w} seconds before calling Page.stopLoading...")
            await asyncio.sleep(w)

            # Check if page still exists (might have been closed due to error during sleep)
            if not self.page or not hasattr(self.page, '_client'):
                logger.debug("Page already closed, skipping stopLoading")
                return

            logger.debug("Issuing stopLoading command...")
            await self.page._client.send('Page.stopLoading')
            logger.debug("stopLoading command sent!")

        async def setup_frame_handlers_on_first_response(event):
            # Only trigger for the main document response
            if event.get('type') == 'Document':
                logger.debug("First response received, setting up frame handlers for forced page stop load.")
                self.page._client.on('Page.frameStartedNavigating', lambda e: asyncio.create_task(handle_frame_navigation(e)))
                self.page._client.on('Page.frameStartedLoading', lambda e: asyncio.create_task(handle_frame_navigation(e)))
                self.page._client.on('Page.frameStoppedLoading', lambda e: logger.debug(f"Frame stopped loading: {e}"))
                logger.debug("First response received, setting up frame handlers for forced page stop load DONE SETUP")
                # De-register this listener - we only need it once
                self.page._client.remove_listener('Network.responseReceived', setup_frame_handlers_on_first_response)

        # Listen for first response to trigger frame handler setup
        self.page._client.on('Network.responseReceived', setup_frame_handlers_on_first_response)

        response = None
        attempt=0
        while not response:
            logger.debug(f"Attempting page fetch {url} attempt {attempt}")
            asyncio.create_task(handle_frame_navigation())
            response = await self.page.goto(url, timeout=0)
            await asyncio.sleep(1 + extra_wait)
            # Check if page still exists before sending command
            if self.page and hasattr(self.page, '_client'):
                await self.page._client.send('Page.stopLoading')

            if response:
                break
            if not response:
                logger.warning("Page did not fetch! trying again!")
            if response is None and attempt>=2:
                logger.warning(f"Content Fetcher > Response object was none (as in, the response from the browser was empty, not just the content) exiting attempt {attempt}")
                raise EmptyReply(url=url, status_code=None)
            attempt+=1

        self.headers = response.headers

        try:
            if self.webdriver_js_execute_code is not None and len(self.webdriver_js_execute_code):
                await self.page.evaluate(self.webdriver_js_execute_code)
        except Exception as e:
            logger.warning("Got exception when running evaluate on custom JS code")
            logger.error(str(e))
            # This can be ok, we will try to grab what we could retrieve
            raise PageUnloadable(url=url, status_code=None, message=str(e))

        try:
            self.status_code = response.status
        except Exception as e:
            # https://github.com/dgtlmoon/changedetection.io/discussions/2122#discussioncomment-8241962
            logger.critical(f"Response from the browser/Playwright did not have a status_code! Response follows.")
            logger.critical(response)
            raise PageUnloadable(url=url, status_code=None, message=str(e))

        if fetch_favicon:
            try:
                self.favicon_blob = await self.page.evaluate(FAVICON_FETCHER_JS)
            except Exception as e:
                logger.error(f"Error fetching FavIcon info {str(e)}, continuing.")

        if self.status_code != 200 and not ignore_status_codes:
            screenshot = await capture_full_page(page=self.page, screenshot_format=self.screenshot_format, watch_uuid=watch_uuid, lock_viewport_elements=self.lock_viewport_elements)

            raise Non200ErrorCodeReceived(url=url, status_code=self.status_code, screenshot=screenshot)

        content = await self.page.content

        if not empty_pages_are_a_change and len(content.strip()) == 0:
            logger.error("Content Fetcher > Content was empty (empty_pages_are_a_change is False), closing browsers")
            raise EmptyReply(url=url, status_code=response.status)

        # Run Browser Steps here
        # @todo not yet supported, we switch to playwright in this case
        #            if self.browser_steps:
        #                self.iterate_browser_steps()


        # So we can find an element on the page where its selector was entered manually (maybe not xPath etc)
        # Setup the xPath/VisualSelector scraper
        if current_include_filters:
            js = json.dumps(current_include_filters)
            await self.page.evaluate(f"var include_filters={js}")
        else:
            await self.page.evaluate(f"var include_filters=''")

        MAX_TOTAL_HEIGHT = int(os.getenv("SCREENSHOT_MAX_HEIGHT", SCREENSHOT_MAX_HEIGHT_DEFAULT))

        self.content = await self.page.content

        # Now take screenshot (scrolling may trigger layout changes, but measurements are already captured)
        logger.debug(f"Screenshot format {self.screenshot_format}")
        self.screenshot = await capture_full_page(page=self.page, screenshot_format=self.screenshot_format, watch_uuid=watch_uuid, lock_viewport_elements=self.lock_viewport_elements)

        # Force garbage collection - pyppeteer base64 decode creates temporary buffers
        import gc
        gc.collect()
        self.xpath_data = await self.page.evaluate(XPATH_ELEMENT_JS, {
            "visualselector_xpath_selectors": visualselector_xpath_selectors,
            "max_height": MAX_TOTAL_HEIGHT
        })
        if not self.xpath_data:
            raise Exception(f"Content Fetcher > xPath scraper failed. Please report this URL so we can fix it :)")


        self.instock_data = await self.page.evaluate(INSTOCK_DATA_JS)

        # It's good to log here in the case that the browser crashes on shutting down but we still get the data we need
        logger.success(f"Fetching '{url}' complete, exiting puppeteer fetch.")

    async def main(self, **kwargs):
        await self.fetch_page(**kwargs)

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

        #@todo make update_worker async which could run any of these content_fetchers within memory and time constraints
        max_time = int(os.getenv('PUPPETEER_MAX_PROCESSING_TIMEOUT_SECONDS', 180))

        # Now we run this properly in async context since we're called from async worker
        try:
            await asyncio.wait_for(self.main(
                current_include_filters=current_include_filters,
                empty_pages_are_a_change=empty_pages_are_a_change,
                fetch_favicon=fetch_favicon,
                ignore_status_codes=ignore_status_codes,
                is_binary=is_binary,
                request_body=request_body,
                request_headers=request_headers,
                request_method=request_method,
                screenshot_format=None,
                timeout=timeout,
                url=url,
                watch_uuid=watch_uuid,
            ), timeout=max_time
            )
        except asyncio.TimeoutError:
            raise (BrowserFetchTimedOut(msg=f"Browser connected but was unable to process the page in {max_time} seconds."))


# Plugin registration for built-in fetcher
class PuppeteerFetcherPlugin:
    """Plugin class that registers the Puppeteer fetcher as a built-in plugin."""

    def register_content_fetcher(self):
        """Register the Puppeteer fetcher"""
        return ('html_webdriver', fetcher)


# Create module-level instance for plugin registration
puppeteer_plugin = PuppeteerFetcherPlugin()
