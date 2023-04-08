from . import Fetcher
from . import exceptions
from . import visualselector_xpath_selectors

import os
import logging
import time

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

    def __init__(self, proxy_override=None):
        super().__init__()
        import json

        # .strip('"') is going to save someone a lot of time when they accidently wrap the env value
        self.browser_type = os.getenv("PLAYWRIGHT_BROWSER_TYPE", 'chromium').strip('"')
        self.command_executor = os.getenv(
            "PLAYWRIGHT_DRIVER_URL",
            'ws://playwright-chrome:3000'
        ).strip('"')

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
            from urllib.parse import urlparse
            parsed = urlparse(self.proxy.get('server'))
            if parsed.username:
                self.proxy['username'] = parsed.username
                self.proxy['password'] = parsed.password

    def screenshot_step(self, step_n=''):
        screenshot = self.page.screenshot(type='jpeg', full_page=True, quality=85)

        if self.browser_steps_screenshot_path is not None:
            destination = os.path.join(self.browser_steps_screenshot_path, 'step_{}.jpeg'.format(step_n))
            logging.debug("Saving step screenshot to {}".format(destination))
            with open(destination, 'wb') as f:
                f.write(screenshot)

    def save_step_html(self, step_n):
        content = self.page.content()
        destination = os.path.join(self.browser_steps_screenshot_path, 'step_{}.html'.format(step_n))
        logging.debug("Saving step HTML to {}".format(destination))
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
            is_binary=False):

        from playwright.sync_api import sync_playwright
        import playwright._impl._api_types
        import json

        self.delete_browser_steps_screenshots()
        response = None
        with sync_playwright() as p:
            browser_type = getattr(p, self.browser_type)

            # Seemed to cause a connection Exception even tho I can see it connect
            # self.browser = browser_type.connect(self.command_executor, timeout=timeout*1000)
            # 60,000 connection timeout only
            browser = browser_type.connect_over_cdp(self.command_executor, timeout=60000)

            # Set user agent to prevent Cloudflare from blocking the browser
            # Use the default one configured in the App.py model that's passed from fetch_site_status.py
            context = browser.new_context(
                user_agent=request_headers['User-Agent'] if request_headers.get('User-Agent') else 'Mozilla/5.0',
                proxy=self.proxy,
                # This is needed to enable JavaScript execution on GitHub and others
                bypass_csp=True,
                # Should be `allow` or `block` - sites like YouTube can transmit large amounts of data via Service Workers
                service_workers=os.getenv('PLAYWRIGHT_SERVICE_WORKERS', 'allow'),
                # Should never be needed
                accept_downloads=False
            )

            self.page = context.new_page()
            if len(request_headers):
                context.set_extra_http_headers(request_headers)

                self.page.set_default_navigation_timeout(90000)
                self.page.set_default_timeout(90000)

                # Listen for all console events and handle errors
                self.page.on("console", lambda msg: print(f"Playwright console: Watch URL: {url} {msg.type}: {msg.text} {msg.args}"))

            # Goto page
            try:
                # Wait_until = commit
                # - `'commit'` - consider operation to be finished when network response is received and the document started loading.
                # Better to not use any smarts from Playwright and just wait an arbitrary number of seconds
                # This seemed to solve nearly all 'TimeoutErrors'
                response = self.page.goto(url, wait_until='commit')
            except playwright._impl._api_types.Error as e:
                # Retry once - https://github.com/browserless/chrome/issues/2485
                # Sometimes errors related to invalid cert's and other can be random
                print ("Content Fetcher > retrying request got error - ", str(e))
                time.sleep(1)
                response = self.page.goto(url, wait_until='commit')

            except Exception as e:
                print ("Content Fetcher > Other exception when page.goto", str(e))
                context.close()
                browser.close()
                raise exceptions.PageUnloadable(url=url, status_code=None, message=str(e))

            # Execute any browser steps
            try:
                extra_wait = int(os.getenv("WEBDRIVER_DELAY_BEFORE_CONTENT_READY", 5)) + self.render_extract_delay
                self.page.wait_for_timeout(extra_wait * 1000)

                if self.webdriver_js_execute_code is not None and len(self.webdriver_js_execute_code):
                    self.page.evaluate(self.webdriver_js_execute_code)

            except playwright._impl._api_types.TimeoutError as e:
                context.close()
                browser.close()
                # This can be ok, we will try to grab what we could retrieve
                pass
            except Exception as e:
                print ("Content Fetcher > Other exception when executing custom JS code", str(e))
                context.close()
                browser.close()
                raise exceptions.PageUnloadable(url=url, status_code=None, message=str(e))

            if response is None:
                context.close()
                browser.close()
                print ("Content Fetcher > Response object was none")
                raise exceptions.EmptyReply(url=url, status_code=None)

            # Run Browser Steps here
            self.iterate_browser_steps()

            extra_wait = int(os.getenv("WEBDRIVER_DELAY_BEFORE_CONTENT_READY", 5)) + self.render_extract_delay
            time.sleep(extra_wait)

            self.content = self.page.content()
            self.status_code = response.status
            if len(self.page.content().strip()) == 0:
                context.close()
                browser.close()
                print ("Content Fetcher > Content was empty")
                raise exceptions.EmptyReply(url=url, status_code=response.status)

            self.status_code = response.status
            self.headers = response.all_headers()

            # So we can find an element on the page where its selector was entered manually (maybe not xPath etc)
            if current_include_filters is not None:
                self.page.evaluate("var include_filters={}".format(json.dumps(current_include_filters)))
            else:
                self.page.evaluate("var include_filters=''")

            self.xpath_data = self.page.evaluate("async () => {" + self.xpath_element_js.replace('%ELEMENTS%', visualselector_xpath_selectors) + "}")
            self.instock_data = self.page.evaluate("async () => {" + self.instock_data_js + "}")

            # Bug 3 in Playwright screenshot handling
            # Some bug where it gives the wrong screenshot size, but making a request with the clip set first seems to solve it
            # JPEG is better here because the screenshots can be very very large

            # Screenshots also travel via the ws:// (websocket) meaning that the binary data is base64 encoded
            # which will significantly increase the IO size between the server and client, it's recommended to use the lowest
            # acceptable screenshot quality here
            try:
                # The actual screenshot
                self.screenshot = self.page.screenshot(type='jpeg', full_page=True, quality=int(os.getenv("PLAYWRIGHT_SCREENSHOT_QUALITY", 72)))
            except Exception as e:
                context.close()
                browser.close()
                raise exceptions.ScreenshotUnavailable(url=url, status_code=None)

            context.close()
            browser.close()
