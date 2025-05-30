import os
import time

from loguru import logger
from changedetectionio.content_fetchers.base import Fetcher

class fetcher(Fetcher):
    if os.getenv("WEBDRIVER_URL"):
        fetcher_description = "WebDriver Chrome/Javascript via '{}'".format(os.getenv("WEBDRIVER_URL"))
    else:
        fetcher_description = "WebDriver Chrome/Javascript"

    proxy = None
    proxy_url = None

    def __init__(self, proxy_override=None, custom_browser_connection_url=None):
        super().__init__()
        from urllib.parse import urlparse
        from selenium.webdriver.common.proxy import Proxy

        # .strip('"') is going to save someone a lot of time when they accidently wrap the env value
        if not custom_browser_connection_url:
            self.browser_connection_url = os.getenv("WEBDRIVER_URL", 'http://browser-chrome:4444/wd/hub').strip('"')
        else:
            self.browser_connection_is_custom = True
            self.browser_connection_url = custom_browser_connection_url


        ##### PROXY SETUP #####

        proxy_sources = [
            self.system_http_proxy,
            self.system_https_proxy,
            os.getenv('webdriver_proxySocks'),
            os.getenv('webdriver_socksProxy'),
            os.getenv('webdriver_proxyHttp'),
            os.getenv('webdriver_httpProxy'),
            os.getenv('webdriver_proxyHttps'),
            os.getenv('webdriver_httpsProxy'),
            os.getenv('webdriver_sslProxy'),
            proxy_override, # last one should override
        ]
        # The built in selenium proxy handling is super unreliable!!! so we just grab which ever proxy setting we can find and throw it in --proxy-server=
        for k in filter(None, proxy_sources):
            if not k:
                continue
            self.proxy_url = k.strip()


    async def run(self,
            url,
            timeout,
            request_headers,
            request_body,
            request_method,
            ignore_status_codes=False,
            current_include_filters=None,
            is_binary=False,
            empty_pages_are_a_change=False):

        import asyncio
        
        # Wrap the entire selenium operation in a thread executor
        def _run_sync():
            from selenium.webdriver.chrome.options import Options as ChromeOptions
            # request_body, request_method unused for now, until some magic in the future happens.

            options = ChromeOptions()

            # Load Chrome options from env
            CHROME_OPTIONS = [
                line.strip()
                for line in os.getenv("CHROME_OPTIONS", "").strip().splitlines()
                if line.strip()
            ]

            for opt in CHROME_OPTIONS:
                options.add_argument(opt)

            # 1. proxy_config /Proxy(proxy_config) selenium object is REALLY unreliable
            # 2. selenium-wire cant be used because the websocket version conflicts with pypeteer-ng
            # 3. selenium only allows ONE runner at a time by default!
            # 4. driver must use quit() or it will continue to block/hold the selenium process!!

            if self.proxy_url:
                options.add_argument(f'--proxy-server={self.proxy_url}')

            from selenium.webdriver.remote.remote_connection import RemoteConnection
            from selenium.webdriver.remote.webdriver import WebDriver as RemoteWebDriver
            driver = None
            try:
                # Create the RemoteConnection and set timeout (e.g., 30 seconds)
                remote_connection = RemoteConnection(
                    self.browser_connection_url,
                )
                remote_connection.set_timeout(30)  # seconds

                # Now create the driver with the RemoteConnection
                driver = RemoteWebDriver(
                    command_executor=remote_connection,
                    options=options
                )

                driver.set_page_load_timeout(int(os.getenv("WEBDRIVER_PAGELOAD_TIMEOUT", 45)))
            except Exception as e:
                if driver:
                    driver.quit()
                raise e

            try:
                driver.get(url)

                if not "--window-size" in os.getenv("CHROME_OPTIONS", ""):
                    driver.set_window_size(1280, 1024)

                driver.implicitly_wait(int(os.getenv("WEBDRIVER_DELAY_BEFORE_CONTENT_READY", 5)))

                if self.webdriver_js_execute_code is not None:
                    driver.execute_script(self.webdriver_js_execute_code)
                    # Selenium doesn't automatically wait for actions as good as Playwright, so wait again
                    driver.implicitly_wait(int(os.getenv("WEBDRIVER_DELAY_BEFORE_CONTENT_READY", 5)))

                # @todo - how to check this? is it possible?
                self.status_code = 200
                # @todo somehow we should try to get this working for WebDriver
                # raise EmptyReply(url=url, status_code=r.status_code)

                # @todo - dom wait loaded?
                import time
                time.sleep(int(os.getenv("WEBDRIVER_DELAY_BEFORE_CONTENT_READY", 5)) + self.render_extract_delay)
                self.content = driver.page_source
                self.headers = {}
                self.screenshot = driver.get_screenshot_as_png()
            except Exception as e:
                driver.quit()
                raise e

            driver.quit()

        # Run the selenium operations in a thread pool to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _run_sync)

