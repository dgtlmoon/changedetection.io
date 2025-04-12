import asyncio
import json
import os
import websockets.exceptions
from urllib.parse import urlparse

from loguru import logger

from changedetectionio.content_fetchers import SCREENSHOT_MAX_HEIGHT_DEFAULT, visualselector_xpath_selectors, \
    SCREENSHOT_SIZE_STITCH_THRESHOLD, SCREENSHOT_DEFAULT_QUALITY, XPATH_ELEMENT_JS, INSTOCK_DATA_JS, \
    SCREENSHOT_MAX_TOTAL_HEIGHT
from changedetectionio.content_fetchers.base import Fetcher, manage_user_agent
from changedetectionio.content_fetchers.exceptions import PageUnloadable, Non200ErrorCodeReceived, EmptyReply, BrowserFetchTimedOut, \
    BrowserConnectError


# Bug 3 in Playwright screenshot handling
# Some bug where it gives the wrong screenshot size, but making a request with the clip set first seems to solve it

# Screenshots also travel via the ws:// (websocket) meaning that the binary data is base64 encoded
# which will significantly increase the IO size between the server and client, it's recommended to use the lowest
# acceptable screenshot quality here
async def capture_full_page(page):
    import os
    import time
    from multiprocessing import Process, Pipe

    start = time.time()

    page_height = await page.evaluate("document.documentElement.scrollHeight")
    page_width = await page.evaluate("document.documentElement.scrollWidth")
    original_viewport = page.viewport

    logger.debug(f"Puppeteer viewport size {page.viewport} page height {page_height} page width {page_width}")

    # Bug 3 in Playwright screenshot handling
    # Some bug where it gives the wrong screenshot size, but making a request with the clip set first seems to solve it
    # JPEG is better here because the screenshots can be very very large

    # Screenshots also travel via the ws:// (websocket) meaning that the binary data is base64 encoded
    # which will significantly increase the IO size between the server and client, it's recommended to use the lowest
    # acceptable screenshot quality here


    step_size = SCREENSHOT_SIZE_STITCH_THRESHOLD # Something that will not cause the GPU to overflow when taking the screenshot
    screenshot_chunks = []
    y = 0
    if page_height > page.viewport['height']:
        if page_height < step_size:
            step_size = page_height # Incase page is bigger than default viewport but smaller than proposed step size
        await page.setViewport({'width': page.viewport['width'], 'height': step_size})

    while y < min(page_height, SCREENSHOT_MAX_TOTAL_HEIGHT):
        await page.evaluate(f"window.scrollTo(0, {y})")
        screenshot_chunks.append(await page.screenshot(type_='jpeg',
                                                       fullPage=False,
                                                       quality=int(os.getenv("SCREENSHOT_QUALITY", 72))))
        y += step_size

    await page.setViewport({'width': original_viewport['width'], 'height': original_viewport['height']})

    if len(screenshot_chunks) > 1:
        from changedetectionio.content_fetchers.screenshot_handler import stitch_images_worker
        logger.debug(f"Screenshot stitching {len(screenshot_chunks)} chunks together")
        parent_conn, child_conn = Pipe()
        p = Process(target=stitch_images_worker, args=(child_conn, screenshot_chunks, page_height, SCREENSHOT_MAX_TOTAL_HEIGHT))
        p.start()
        screenshot = parent_conn.recv_bytes()
        p.join()
        logger.debug(
            f"Screenshot (chunked/stitched) - Page height: {page_height} Capture height: {SCREENSHOT_MAX_TOTAL_HEIGHT} - Stitched together in {time.time() - start:.2f}s")

        screenshot_chunks = None
        return screenshot

    logger.debug(
        f"Screenshot Page height: {page_height} Capture height: {SCREENSHOT_MAX_TOTAL_HEIGHT} - Stitched together in {time.time() - start:.2f}s")
    return screenshot_chunks[0]


class fetcher(Fetcher):
    fetcher_description = "Puppeteer/direct {}/Javascript".format(
        os.getenv("PLAYWRIGHT_BROWSER_TYPE", 'chromium').capitalize()
    )
    if os.getenv("PLAYWRIGHT_DRIVER_URL"):
        fetcher_description += " via '{}'".format(os.getenv("PLAYWRIGHT_DRIVER_URL"))

    browser_type = ''
    command_executor = ''

    proxy = None

    def __init__(self, proxy_override=None, custom_browser_connection_url=None):
        super().__init__()

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

    # def screenshot_step(self, step_n=''):
    #     screenshot = self.page.screenshot(type='jpeg', full_page=True, quality=85)
    #
    #     if self.browser_steps_screenshot_path is not None:
    #         destination = os.path.join(self.browser_steps_screenshot_path, 'step_{}.jpeg'.format(step_n))
    #         logger.debug(f"Saving step screenshot to {destination}")
    #         with open(destination, 'wb') as f:
    #             f.write(screenshot)
    #
    # def save_step_html(self, step_n):
    #     content = self.page.content()
    #     destination = os.path.join(self.browser_steps_screenshot_path, 'step_{}.html'.format(step_n))
    #     logger.debug(f"Saving step HTML to {destination}")
    #     with open(destination, 'w') as f:
    #         f.write(content)

    async def fetch_page(self,
                         url,
                         timeout,
                         request_headers,
                         request_body,
                         request_method,
                         ignore_status_codes,
                         current_include_filters,
                         is_binary,
                         empty_pages_are_a_change
                         ):

        self.delete_browser_steps_screenshots()
        extra_wait = int(os.getenv("WEBDRIVER_DELAY_BEFORE_CONTENT_READY", 5)) + self.render_extract_delay

        from pyppeteer import Pyppeteer
        pyppeteer_instance = Pyppeteer()

        # Connect directly using the specified browser_ws_endpoint
        # @todo timeout
        try:
            browser = await pyppeteer_instance.connect(browserWSEndpoint=self.browser_connection_url,
                                                       ignoreHTTPSErrors=True
                                                       )
        except websockets.exceptions.InvalidStatusCode as e:
            raise BrowserConnectError(msg=f"Error while trying to connect the browser, Code {e.status_code} (check your access, whitelist IP, password etc)")
        except websockets.exceptions.InvalidURI:
            raise BrowserConnectError(msg=f"Error connecting to the browser, check your browser connection address (should be ws:// or wss://")
        except Exception as e:
            raise BrowserConnectError(msg=f"Error connecting to the browser {str(e)}")

        # Better is to launch chrome with the URL as arg
        # non-headless - newPage() will launch an extra tab/window, .browser should already contain 1 page/tab
        # headless - ask a new page
        self.page = (pages := await browser.pages) and len(pages) or await browser.newPage()

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

        response = await self.page.goto(url, waitUntil="load")


        if response is None:
            await self.page.close()
            await browser.close()
            logger.warning("Content Fetcher > Response object was none (as in, the response from the browser was empty, not just the content)")
            raise EmptyReply(url=url, status_code=None)

        self.headers = response.headers

        try:
            if self.webdriver_js_execute_code is not None and len(self.webdriver_js_execute_code):
                await self.page.evaluate(self.webdriver_js_execute_code)
        except Exception as e:
            logger.warning("Got exception when running evaluate on custom JS code")
            logger.error(str(e))
            await self.page.close()
            await browser.close()
            # This can be ok, we will try to grab what we could retrieve
            raise PageUnloadable(url=url, status_code=None, message=str(e))

        try:
            self.status_code = response.status
        except Exception as e:
            # https://github.com/dgtlmoon/changedetection.io/discussions/2122#discussioncomment-8241962
            logger.critical(f"Response from the browser/Playwright did not have a status_code! Response follows.")
            logger.critical(response)
            await self.page.close()
            await browser.close()
            raise PageUnloadable(url=url, status_code=None, message=str(e))

        if self.status_code != 200 and not ignore_status_codes:
            screenshot = await capture_full_page(page=self.page)

            raise Non200ErrorCodeReceived(url=url, status_code=self.status_code, screenshot=screenshot)

        content = await self.page.content

        if not empty_pages_are_a_change and len(content.strip()) == 0:
            logger.error("Content Fetcher > Content was empty (empty_pages_are_a_change is False), closing browsers")
            await self.page.close()
            await browser.close()
            raise EmptyReply(url=url, status_code=response.status)

        # Run Browser Steps here
        # @todo not yet supported, we switch to playwright in this case
        #            if self.browser_steps_get_valid_steps():
        #                self.iterate_browser_steps()

        await asyncio.sleep(1 + extra_wait)

        # So we can find an element on the page where its selector was entered manually (maybe not xPath etc)
        # Setup the xPath/VisualSelector scraper
        if current_include_filters:
            js = json.dumps(current_include_filters)
            await self.page.evaluate(f"var include_filters={js}")
        else:
            await self.page.evaluate(f"var include_filters=''")

        MAX_TOTAL_HEIGHT = int(os.getenv("SCREENSHOT_MAX_HEIGHT", SCREENSHOT_MAX_HEIGHT_DEFAULT))
        self.xpath_data = await self.page.evaluate(XPATH_ELEMENT_JS, {
            "visualselector_xpath_selectors": visualselector_xpath_selectors,
            "max_height": MAX_TOTAL_HEIGHT
        })
        if not self.xpath_data:
            raise Exception(f"Content Fetcher > xPath scraper failed. Please report this URL so we can fix it :)")

        self.instock_data = await self.page.evaluate(INSTOCK_DATA_JS)

        self.content = await self.page.content

        self.screenshot = await capture_full_page(page=self.page)

        # It's good to log here in the case that the browser crashes on shutting down but we still get the data we need
        logger.success(f"Fetching '{url}' complete, closing page")
        await self.page.close()
        logger.success(f"Fetching '{url}' complete, closing browser")
        await browser.close()
        logger.success(f"Fetching '{url}' complete, exiting puppeteer fetch.")

    async def main(self, **kwargs):
        await self.fetch_page(**kwargs)

    def run(self, url, timeout, request_headers, request_body, request_method, ignore_status_codes=False,
            current_include_filters=None, is_binary=False, empty_pages_are_a_change=False):

        #@todo make update_worker async which could run any of these content_fetchers within memory and time constraints
        max_time = os.getenv('PUPPETEER_MAX_PROCESSING_TIMEOUT_SECONDS', 180)

        # This will work in 3.10 but not >= 3.11 because 3.11 wants tasks only
        try:
            asyncio.run(asyncio.wait_for(self.main(
                url=url,
                timeout=timeout,
                request_headers=request_headers,
                request_body=request_body,
                request_method=request_method,
                ignore_status_codes=ignore_status_codes,
                current_include_filters=current_include_filters,
                is_binary=is_binary,
                empty_pages_are_a_change=empty_pages_are_a_change
            ), timeout=max_time))
        except asyncio.TimeoutError:
            raise(BrowserFetchTimedOut(msg=f"Browser connected but was unable to process the page in {max_time} seconds."))

