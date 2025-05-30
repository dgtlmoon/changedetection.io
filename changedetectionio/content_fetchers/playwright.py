import json
import os
from urllib.parse import urlparse

from loguru import logger

from changedetectionio.content_fetchers import SCREENSHOT_MAX_HEIGHT_DEFAULT, visualselector_xpath_selectors, \
    SCREENSHOT_SIZE_STITCH_THRESHOLD, SCREENSHOT_MAX_TOTAL_HEIGHT, XPATH_ELEMENT_JS, INSTOCK_DATA_JS
from changedetectionio.content_fetchers.base import Fetcher, manage_user_agent
from changedetectionio.content_fetchers.exceptions import PageUnloadable, Non200ErrorCodeReceived, EmptyReply, ScreenshotUnavailable
from changedetectionio.content_fetchers.playwright_manager import get_playwright_manager


# Legacy sync function - kept for compatibility but not used
def capture_full_page(page):
    """Legacy sync capture function - kept for compatibility"""
    import os
    import time
    from multiprocessing import Process, Pipe

    start = time.time()

    page_height = page.evaluate("document.documentElement.scrollHeight")
    page_width = page.evaluate("document.documentElement.scrollWidth")
    original_viewport = page.viewport_size

    logger.debug(f"Playwright viewport size {page.viewport_size} page height {page_height} page width {page_width}")

    # Use an approach similar to puppeteer: set a larger viewport and take screenshots in chunks
    step_size = SCREENSHOT_SIZE_STITCH_THRESHOLD # Size that won't cause GPU to overflow
    screenshot_chunks = []
    y = 0

    if page_height > page.viewport_size['height']:
        if page_height < step_size:
            step_size = page_height # Incase page is bigger than default viewport but smaller than proposed step size
        logger.debug(f"Setting bigger viewport to step through large page width W{page.viewport_size['width']}xH{step_size} because page_height > viewport_size")
        # Set viewport to a larger size to capture more content at once
        page.set_viewport_size({'width': page.viewport_size['width'], 'height': step_size})

    # Capture screenshots in chunks up to the max total height
    while y < min(page_height, SCREENSHOT_MAX_TOTAL_HEIGHT):
        page.request_gc()
        page.evaluate(f"window.scrollTo(0, {y})")
        page.request_gc()
        screenshot_chunks.append(page.screenshot(
            type="jpeg",
            full_page=False,
            quality=int(os.getenv("SCREENSHOT_QUALITY", 72))
        ))
        y += step_size
        page.request_gc()

    # Restore original viewport size
    page.set_viewport_size({'width': original_viewport['width'], 'height': original_viewport['height']})

    # If we have multiple chunks, stitch them together
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
        # Explicit cleanup
        del screenshot_chunks
        del p
        del parent_conn, child_conn
        screenshot_chunks = None
        return screenshot

    logger.debug(
        f"Screenshot Page height: {page_height} Capture height: {SCREENSHOT_MAX_TOTAL_HEIGHT} - Single screenshot captured in {time.time() - start:.2f}s")

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
        """Legacy screenshot step method - not used with new manager"""
        super().screenshot_step(step_n=step_n)
        # This would need to be reimplemented with the manager if browser steps are used
        logger.warning("screenshot_step called - browser steps may need updating for new manager")

    def save_step_html(self, step_n):
        """Legacy save step HTML method - not used with new manager"""
        super().save_step_html(step_n=step_n)
        # This would need to be reimplemented with the manager if browser steps are used
        logger.warning("save_step_html called - browser steps may need updating for new manager")

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
        """
        Main run method - now uses PlaywrightManager instead of creating its own async context.
        This method is synchronous and thread-safe.
        """
        
        self.delete_browser_steps_screenshots()
        
        try:
            # Get the singleton manager
            playwright_manager = get_playwright_manager()
            
            # Prepare all the parameters for the manager
            fetch_params = {
                'timeout': timeout,
                'request_headers': request_headers,
                'request_body': request_body,
                'request_method': request_method,
                'ignore_status_codes': ignore_status_codes,
                'current_include_filters': current_include_filters,
                'is_binary': is_binary,
                'empty_pages_are_a_change': empty_pages_are_a_change,
                'proxy_override': self.proxy,
                'webdriver_js_execute_code': self.webdriver_js_execute_code,
                'browser_steps': None,  # TODO: Implement browser steps integration
                'render_extract_delay': self.render_extract_delay
            }
            
            # Use the manager to fetch the page
            result = playwright_manager.fetch_page(url, **fetch_params)
            
            # Extract results into instance variables (maintaining compatibility)
            self.content = result['content']
            self.status_code = result['status_code']
            self.screenshot = result['screenshot']
            self.headers = result['headers']
            self.xpath_data = result['xpath_data']
            self.instock_data = result['instock_data']
            
            logger.debug(f"Playwright fetch completed successfully for {url}")
            
            return self.content
            
        except Exception as e:
            logger.error(f"Playwright fetch failed for {url}: {e}")
            self.error = str(e)
            raise
