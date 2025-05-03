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

        proxy_config = {}

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

        for k in filter(None, proxy_sources):
            if not k:
                continue
            parsed = urlparse(k.strip())
            scheme = parsed.scheme.lower()

            if scheme.startswith('socks'):
                proxy_config.update({
                    'socksProxy': f"{parsed.hostname}:{parsed.port}",
                    'socksVersion': 4 if 'socks4' in scheme else 5,
                    'socksUsername': parsed.username,
                    'socksPassword': parsed.password,
                })

            elif scheme == 'http':
                proxy_config['httpProxy'] = f"{parsed.hostname}:{parsed.port}"

            elif scheme == 'https':
                proxy_config['sslProxy'] = f"{parsed.hostname}:{parsed.port}"

           # common auth for http/https
            if scheme in ('http', 'https'):
                if parsed.username:
                    proxy_config['proxyUser'] = parsed.username
                if parsed.username:
                    proxy_config['proxyPassword'] = parsed.password

        if proxy_config:
            proxy_config['proxyType'] = 'MANUAL'
            self.proxy = Proxy(proxy_config)


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

        from selenium import webdriver
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

        if self.proxy:
            options.proxy = self.proxy

        from selenium.webdriver.remote.remote_connection import RemoteConnection
        from selenium.webdriver.remote.webdriver import WebDriver as RemoteWebDriver

        try:
            # Create the RemoteConnection and set timeout (e.g., 30 seconds)
            remote_connection = RemoteConnection(
                self.browser_connection_url,
            )
            remote_connection.set_timeout(30)  # seconds

            # Now create the driver with the RemoteConnection
            self.driver = RemoteWebDriver(
                command_executor=remote_connection,
                options=options
            )

            self.driver.set_page_load_timeout(int(os.getenv("WEBDRIVER_PAGELOAD_TIMEOUT", 45)))
        except Exception as e:
            self.driver.quit()
            raise e

        try:
            self.driver.get(url)

            if not "--window-size" in os.getenv("CHROME_OPTIONS", ""):
                self.driver.set_window_size(1280, 1024)

            self.driver.implicitly_wait(int(os.getenv("WEBDRIVER_DELAY_BEFORE_CONTENT_READY", 5)))

            if self.webdriver_js_execute_code is not None:
                self.driver.execute_script(self.webdriver_js_execute_code)
                # Selenium doesn't automatically wait for actions as good as Playwright, so wait again
                self.driver.implicitly_wait(int(os.getenv("WEBDRIVER_DELAY_BEFORE_CONTENT_READY", 5)))

            # @todo - how to check this? is it possible?
            self.status_code = 200
            # @todo somehow we should try to get this working for WebDriver
            # raise EmptyReply(url=url, status_code=r.status_code)

            # @todo - dom wait loaded?
            time.sleep(int(os.getenv("WEBDRIVER_DELAY_BEFORE_CONTENT_READY", 5)) + self.render_extract_delay)
            self.content = self.driver.page_source
            self.headers = {}
            self.screenshot = self.driver.get_screenshot_as_png()
        except Exception as e:
            self.driver.quit()
            raise e

        self.driver.quit()

