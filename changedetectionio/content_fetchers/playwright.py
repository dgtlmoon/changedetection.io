import json
import os
from urllib.parse import urlparse

from loguru import logger

from changedetectionio.content_fetchers import SCREENSHOT_MAX_HEIGHT_DEFAULT, visualselector_xpath_selectors, \
    SCREENSHOT_SIZE_STITCH_THRESHOLD, SCREENSHOT_MAX_TOTAL_HEIGHT, SCREENSHOT_DEFAULT_QUALITY, XPATH_ELEMENT_JS, INSTOCK_DATA_JS
from changedetectionio.content_fetchers.screenshot_handler import stitch_images_worker
from changedetectionio.content_fetchers.base import Fetcher, manage_user_agent
from changedetectionio.content_fetchers.exceptions import PageUnloadable, Non200ErrorCodeReceived, EmptyReply, ScreenshotUnavailable



def capture_full_page(page):
    import os
    import time
    from multiprocessing import Process, Pipe

    start = time.time()

    page_height = page.evaluate("document.documentElement.scrollHeight")

    logger.debug(f"Playwright viewport size {page.viewport_size}")

    ############################################################
    #### SCREENSHOT FITS INTO ONE SNAPSHOT (SMALLER PAGES) #####
    ############################################################

    # Optimization to avoid unnecessary stitching if we can avoid it
    # Use the default screenshot method for smaller pages to take advantage
    # of GPU and native playwright screenshot optimizations
    # - No PIL needed here, no danger of memory leaks, no sub process required
    if (page_height < SCREENSHOT_SIZE_STITCH_THRESHOLD and page_height < SCREENSHOT_MAX_TOTAL_HEIGHT ):
        logger.debug("Using default screenshot method")
        page.request_gc()
        screenshot = page.screenshot(
            type="jpeg",
            quality=int(os.getenv("SCREENSHOT_QUALITY", SCREENSHOT_DEFAULT_QUALITY)),
            full_page=True,
        )
        page.request_gc()
        logger.debug(f"Screenshot captured in {time.time() - start:.2f}s")
        return screenshot



    ###################################################################################
    #### CASE FOR LARGE SCREENSHOTS THAT NEED TO BE TRIMMED DUE TO MEMORY ISSUES  #####
    ###################################################################################
    # - PIL can easily allocate memory and not release it cleanly
    # - Fetching screenshot from playwright seems  OK
    # Image.new is leaky even with .close()
    # So lets prepare all the data chunks and farm it out to a subprocess for clean memory handling

    logger.debug(
        "Using stitching method for large screenshot because page height exceeds threshold"
    )

    # Limit the total capture height
    capture_height = min(page_height, SCREENSHOT_MAX_TOTAL_HEIGHT)

    # Calculate number of chunks needed using ORIGINAL viewport height
    num_chunks = (capture_height + page.viewport_size['height'] - 1) // page.viewport_size['height']
    screenshot_chunks = []

    # Track cumulative paste position
    y_offset = 0
    for _ in range(num_chunks):

        page.request_gc()
        page.evaluate(f"window.scrollTo(0, {y_offset})")
        page.request_gc()
        h = min(page.viewport_size['height'], capture_height - y_offset)
        screenshot_chunks.append(page.screenshot(
                type="jpeg",
                clip={
                    "x": 0,
                    "y": 0,
                    "width": page.viewport_size['width'],
                    "height": h,
                },
                quality=int(os.getenv("SCREENSHOT_QUALITY", SCREENSHOT_DEFAULT_QUALITY)),
            ))

        y_offset += h # maybe better to inspect the image here?
        page.request_gc()

    # PIL can leak memory in various situations, assign the work to a subprocess for totally clean handling

    parent_conn, child_conn = Pipe()
    p = Process(target=stitch_images_worker, args=(child_conn, screenshot_chunks, page_height, capture_height))
    p.start()
    result = parent_conn.recv_bytes()
    p.join()

    screenshot_chunks = None
    logger.debug(f"Screenshot - Page height: {page_height} Capture height: {capture_height} - Stitched together in {time.time() - start:.2f}s")

    return result


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

    def __init__(self, proxy_override=None, custom_browser_connection_url=None):
        super().__init__()

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

    def screenshot_step(self, step_n=''):
        super().screenshot_step(step_n=step_n)
        screenshot = capture_full_page(page=self.page)


        if self.browser_steps_screenshot_path is not None:
            destination = os.path.join(self.browser_steps_screenshot_path, 'step_{}.jpeg'.format(step_n))
            logger.debug(f"Saving step screenshot to {destination}")
            with open(destination, 'wb') as f:
                f.write(screenshot)

    def save_step_html(self, step_n):
        super().save_step_html(step_n=step_n)
        content = self.page.content()
        destination = os.path.join(self.browser_steps_screenshot_path, 'step_{}.html'.format(step_n))
        logger.debug(f"Saving step HTML to {destination}")
        with open(destination, 'w') as f:
            f.write(content)

    def run(self,
            url,
            timeout,
            request_headers,
            request_body,
            request_method,
            ignore_status_codes=False,
            current_include_filters=None,
            is_binary=False,
            empty_pages_are_a_change=False):

        from playwright.sync_api import sync_playwright
        import playwright._impl._errors
        import time
        self.delete_browser_steps_screenshots()
        response = None

        with sync_playwright() as p:
            browser_type = getattr(p, self.browser_type)

            # Seemed to cause a connection Exception even tho I can see it connect
            # self.browser = browser_type.connect(self.command_executor, timeout=timeout*1000)
            # 60,000 connection timeout only
            browser = browser_type.connect_over_cdp(self.browser_connection_url, timeout=60000)

            # SOCKS5 with authentication is not supported (yet)
            # https://github.com/microsoft/playwright/issues/10567

            # Set user agent to prevent Cloudflare from blocking the browser
            # Use the default one configured in the App.py model that's passed from fetch_site_status.py
            context = browser.new_context(
                accept_downloads=False,  # Should never be needed
                bypass_csp=True,  # This is needed to enable JavaScript execution on GitHub and others
                extra_http_headers=request_headers,
                ignore_https_errors=True,
                proxy=self.proxy,
                service_workers=os.getenv('PLAYWRIGHT_SERVICE_WORKERS', 'allow'), # Should be `allow` or `block` - sites like YouTube can transmit large amounts of data via Service Workers
                user_agent=manage_user_agent(headers=request_headers),
            )

            self.page = context.new_page()

            # Listen for all console events and handle errors
            self.page.on("console", lambda msg: print(f"Playwright console: Watch URL: {url} {msg.type}: {msg.text} {msg.args}"))

            # Re-use as much code from browser steps as possible so its the same
            from changedetectionio.blueprint.browser_steps.browser_steps import steppable_browser_interface
            browsersteps_interface = steppable_browser_interface(start_url=url)
            browsersteps_interface.page = self.page

            response = browsersteps_interface.action_goto_url(value=url)
            self.headers = response.all_headers()

            if response is None:
                context.close()
                browser.close()
                logger.debug("Content Fetcher > Response object from the browser communication was none")
                raise EmptyReply(url=url, status_code=None)

            try:
                if self.webdriver_js_execute_code is not None and len(self.webdriver_js_execute_code):
                    browsersteps_interface.action_execute_js(value=self.webdriver_js_execute_code, selector=None)
            except playwright._impl._errors.TimeoutError as e:
                context.close()
                browser.close()
                # This can be ok, we will try to grab what we could retrieve
                pass
            except Exception as e:
                logger.debug(f"Content Fetcher > Other exception when executing custom JS code {str(e)}")
                context.close()
                browser.close()
                raise PageUnloadable(url=url, status_code=None, message=str(e))

            extra_wait = int(os.getenv("WEBDRIVER_DELAY_BEFORE_CONTENT_READY", 5)) + self.render_extract_delay
            self.page.wait_for_timeout(extra_wait * 1000)

            try:
                self.status_code = response.status
            except Exception as e:
                # https://github.com/dgtlmoon/changedetection.io/discussions/2122#discussioncomment-8241962
                logger.critical(f"Response from the browser/Playwright did not have a status_code! Response follows.")
                logger.critical(response)
                context.close()
                browser.close()
                raise PageUnloadable(url=url, status_code=None, message=str(e))

            if self.status_code != 200 and not ignore_status_codes:
                screenshot = capture_full_page(self.page)
                raise Non200ErrorCodeReceived(url=url, status_code=self.status_code, screenshot=screenshot)

            if not empty_pages_are_a_change and len(self.page.content().strip()) == 0:
                logger.debug("Content Fetcher > Content was empty, empty_pages_are_a_change = False")
                context.close()
                browser.close()
                raise EmptyReply(url=url, status_code=response.status)

            # Run Browser Steps here
            if self.browser_steps_get_valid_steps():
                self.iterate_browser_steps(start_url=url)

            self.page.wait_for_timeout(extra_wait * 1000)

            now = time.time()
            # So we can find an element on the page where its selector was entered manually (maybe not xPath etc)
            if current_include_filters is not None:
                self.page.evaluate("var include_filters={}".format(json.dumps(current_include_filters)))
            else:
                self.page.evaluate("var include_filters=''")
            self.page.request_gc()

            # request_gc before and after evaluate to free up memory
            # @todo browsersteps etc
            MAX_TOTAL_HEIGHT = int(os.getenv("SCREENSHOT_MAX_HEIGHT", SCREENSHOT_MAX_HEIGHT_DEFAULT))
            self.xpath_data = self.page.evaluate(XPATH_ELEMENT_JS, {
                "visualselector_xpath_selectors": visualselector_xpath_selectors,
                "max_height": MAX_TOTAL_HEIGHT
            })
            self.page.request_gc()

            self.instock_data = self.page.evaluate(INSTOCK_DATA_JS)
            self.page.request_gc()

            self.content = self.page.content()
            logger.debug(f"Scrape xPath element data in browser done in {time.time() - now:.2f}s")

            # Bug 3 in Playwright screenshot handling
            # Some bug where it gives the wrong screenshot size, but making a request with the clip set first seems to solve it
            # JPEG is better here because the screenshots can be very very large

            # Screenshots also travel via the ws:// (websocket) meaning that the binary data is base64 encoded
            # which will significantly increase the IO size between the server and client, it's recommended to use the lowest
            # acceptable screenshot quality here
            try:
                # The actual screenshot - this always base64 and needs decoding! horrible! huge CPU usage
                self.screenshot = capture_full_page(page=self.page)

            except Exception as e:
                # It's likely the screenshot was too long/big and something crashed
                raise ScreenshotUnavailable(url=url, status_code=self.status_code)
            finally:
                # Request garbage collection one more time before closing
                try:
                    self.page.request_gc()
                except:
                    pass
                
                # Clean up resources properly
                context.close()
                browser.close()
