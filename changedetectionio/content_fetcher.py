from abc import abstractmethod
from distutils.util import strtobool
from urllib.parse import urlparse
import chardet
import hashlib
import json
import os
import requests
import sys
import time
import urllib.parse
from loguru import logger

visualselector_xpath_selectors = 'div,span,form,table,tbody,tr,td,a,p,ul,li,h1,h2,h3,h4, header, footer, section, article, aside, details, main, nav, section, summary'


class Non200ErrorCodeReceived(Exception):
    def __init__(self, status_code, url, screenshot=None, xpath_data=None, page_html=None):
        # Set this so we can use it in other parts of the app
        self.status_code = status_code
        self.url = url
        self.screenshot = screenshot
        self.xpath_data = xpath_data
        self.page_text = None

        if page_html:
            from changedetectionio import html_tools
            self.page_text = html_tools.html_to_text(page_html)
        return


class checksumFromPreviousCheckWasTheSame(Exception):
    def __init__(self):
        return


class JSActionExceptions(Exception):
    def __init__(self, status_code, url, screenshot, message=''):
        self.status_code = status_code
        self.url = url
        self.screenshot = screenshot
        self.message = message
        return


class BrowserStepsStepException(Exception):
    def __init__(self, step_n, original_e):
        self.step_n = step_n
        self.original_e = original_e
        logger.debug(f"Browser Steps exception at step {self.step_n} {str(original_e)}")
        return


# @todo - make base Exception class that announces via logger()
class PageUnloadable(Exception):
    def __init__(self, status_code=None, url='', message='', screenshot=False):
        # Set this so we can use it in other parts of the app
        self.status_code = status_code
        self.url = url
        self.screenshot = screenshot
        self.message = message
        return

class BrowserStepsInUnsupportedFetcher(Exception):
    def __init__(self, url):
        self.url = url
        return

class EmptyReply(Exception):
    def __init__(self, status_code, url, screenshot=None):
        # Set this so we can use it in other parts of the app
        self.status_code = status_code
        self.url = url
        self.screenshot = screenshot
        return


class ScreenshotUnavailable(Exception):
    def __init__(self, status_code, url, page_html=None):
        # Set this so we can use it in other parts of the app
        self.status_code = status_code
        self.url = url
        if page_html:
            from html_tools import html_to_text
            self.page_text = html_to_text(page_html)
        return


class ReplyWithContentButNoText(Exception):
    def __init__(self, status_code, url, screenshot=None, has_filters=False, html_content=''):
        # Set this so we can use it in other parts of the app
        self.status_code = status_code
        self.url = url
        self.screenshot = screenshot
        self.has_filters = has_filters
        self.html_content = html_content
        return


class Fetcher():
    browser_connection_is_custom = None
    browser_connection_url = None
    browser_steps = None
    browser_steps_screenshot_path = None
    content = None
    error = None
    fetcher_description = "No description"
    headers = {}
    instock_data = None
    instock_data_js = ""
    status_code = None
    webdriver_js_execute_code = None
    xpath_data = None
    xpath_element_js = ""

    # Will be needed in the future by the VisualSelector, always get this where possible.
    screenshot = False
    system_http_proxy = os.getenv('HTTP_PROXY')
    system_https_proxy = os.getenv('HTTPS_PROXY')

    # Time ONTOP of the system defined env minimum time
    render_extract_delay = 0

    def __init__(self):
        from pkg_resources import resource_string
        # The code that scrapes elements and makes a list of elements/size/position to click on in the VisualSelector
        self.xpath_element_js = resource_string(__name__, "res/xpath_element_scraper.js").decode('utf-8')
        self.instock_data_js = resource_string(__name__, "res/stock-not-in-stock.js").decode('utf-8')

    @abstractmethod
    def get_error(self):
        return self.error

    @abstractmethod
    def run(self,
            url,
            timeout,
            request_headers,
            request_body,
            request_method,
            ignore_status_codes=False,
            current_include_filters=None,
            is_binary=False):
        # Should set self.error, self.status_code and self.content
        pass

    @abstractmethod
    def quit(self):
        return

    @abstractmethod
    def get_last_status_code(self):
        return self.status_code

    @abstractmethod
    def screenshot_step(self, step_n):
        return None

    @abstractmethod
    # Return true/false if this checker is ready to run, in the case it needs todo some special config check etc
    def is_ready(self):
        return True

    def get_all_headers(self):
        """
        Get all headers but ensure all keys are lowercase
        :return:
        """
        return {k.lower(): v for k, v in self.headers.items()}

    def browser_steps_get_valid_steps(self):
        if self.browser_steps is not None and len(self.browser_steps):
            valid_steps = filter(
                lambda s: (s['operation'] and len(s['operation']) and s['operation'] != 'Choose one' and s['operation'] != 'Goto site'),
                self.browser_steps)

            return valid_steps

        return None

    def iterate_browser_steps(self):
        from changedetectionio.blueprint.browser_steps.browser_steps import steppable_browser_interface
        from playwright._impl._errors import TimeoutError, Error
        from jinja2 import Environment
        jinja2_env = Environment(extensions=['jinja2_time.TimeExtension'])

        step_n = 0

        if self.browser_steps is not None and len(self.browser_steps):
            interface = steppable_browser_interface()
            interface.page = self.page
            valid_steps = self.browser_steps_get_valid_steps()

            for step in valid_steps:
                step_n += 1
                logger.debug(f">> Iterating check - browser Step n {step_n} - {step['operation']}...")
                self.screenshot_step("before-" + str(step_n))
                self.save_step_html("before-" + str(step_n))
                try:
                    optional_value = step['optional_value']
                    selector = step['selector']
                    # Support for jinja2 template in step values, with date module added
                    if '{%' in step['optional_value'] or '{{' in step['optional_value']:
                        optional_value = str(jinja2_env.from_string(step['optional_value']).render())
                    if '{%' in step['selector'] or '{{' in step['selector']:
                        selector = str(jinja2_env.from_string(step['selector']).render())

                    getattr(interface, "call_action")(action_name=step['operation'],
                                                      selector=selector,
                                                      optional_value=optional_value)
                    self.screenshot_step(step_n)
                    self.save_step_html(step_n)
                except (Error, TimeoutError) as e:
                    logger.debug(str(e))
                    # Stop processing here
                    raise BrowserStepsStepException(step_n=step_n, original_e=e)

    # It's always good to reset these
    def delete_browser_steps_screenshots(self):
        import glob
        if self.browser_steps_screenshot_path is not None:
            dest = os.path.join(self.browser_steps_screenshot_path, 'step_*.jpeg')
            files = glob.glob(dest)
            for f in files:
                if os.path.isfile(f):
                    os.unlink(f)


#   Maybe for the future, each fetcher provides its own diff output, could be used for text, image
#   the current one would return javascript output (as we use JS to generate the diff)
#
def available_fetchers():
    # See the if statement at the bottom of this file for how we switch between playwright and webdriver
    import inspect
    p = []
    for name, obj in inspect.getmembers(sys.modules[__name__], inspect.isclass):
        if inspect.isclass(obj):
            # @todo html_ is maybe better as fetcher_ or something
            # In this case, make sure to edit the default one in store.py and fetch_site_status.py
            if name.startswith('html_'):
                t = tuple([name, obj.fetcher_description])
                p.append(t)

    return p


class base_html_playwright(Fetcher):
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
        screenshot = self.page.screenshot(type='jpeg', full_page=True, quality=85)

        if self.browser_steps_screenshot_path is not None:
            destination = os.path.join(self.browser_steps_screenshot_path, 'step_{}.jpeg'.format(step_n))
            logger.debug(f"Saving step screenshot to {destination}")
            with open(destination, 'wb') as f:
                f.write(screenshot)

    def save_step_html(self, step_n):
        content = self.page.content()
        destination = os.path.join(self.browser_steps_screenshot_path, 'step_{}.html'.format(step_n))
        logger.debug(f"Saving step HTML to {destination}")
        with open(destination, 'w') as f:
            f.write(content)

    def run_fetch_browserless_puppeteer(self,
            url,
            timeout,
            request_headers,
            request_body,
            request_method,
            ignore_status_codes=False,
            current_include_filters=None,
            is_binary=False):

        from pkg_resources import resource_string

        extra_wait_ms = (int(os.getenv("WEBDRIVER_DELAY_BEFORE_CONTENT_READY", 5)) + self.render_extract_delay) * 1000

        self.xpath_element_js = self.xpath_element_js.replace('%ELEMENTS%', visualselector_xpath_selectors)
        code = resource_string(__name__, "res/puppeteer_fetch.js").decode('utf-8')
        # In the future inject this is a proper JS package
        code = code.replace('%xpath_scrape_code%', self.xpath_element_js)
        code = code.replace('%instock_scrape_code%', self.instock_data_js)

        from requests.exceptions import ConnectTimeout, ReadTimeout
        wait_browserless_seconds = 240

        browserless_function_url = os.getenv('BROWSERLESS_FUNCTION_URL')
        from urllib.parse import urlparse
        if not browserless_function_url:
            # Convert/try to guess from PLAYWRIGHT_DRIVER_URL
            o = urlparse(os.getenv('PLAYWRIGHT_DRIVER_URL'))
            browserless_function_url = o._replace(scheme="http")._replace(path="function").geturl()


        # Append proxy connect string
        if self.proxy:
            # Remove username/password if it exists in the URL or you will receive "ERR_NO_SUPPORTED_PROXIES" error
            # Actual authentication handled by Puppeteer/node
            o = urlparse(self.proxy.get('server'))
            proxy_url = urllib.parse.quote(o._replace(netloc="{}:{}".format(o.hostname, o.port)).geturl())
            browserless_function_url = f"{browserless_function_url}&--proxy-server={proxy_url}"

        try:
            amp = '&' if '?' in browserless_function_url else '?'
            response = requests.request(
                method="POST",
                json={
                    "code": code,
                    "context": {
                        # Very primitive disk cache - USE WITH EXTREME CAUTION
                        # Run browserless container  with -e "FUNCTION_BUILT_INS=[\"fs\",\"crypto\"]"
                        'disk_cache_dir': os.getenv("PUPPETEER_DISK_CACHE", False), # or path to disk cache ending in /, ie /tmp/cache/
                        'execute_js': self.webdriver_js_execute_code,
                        'extra_wait_ms': extra_wait_ms,
                        'include_filters': current_include_filters,
                        'req_headers': request_headers,
                        'screenshot_quality': int(os.getenv("PLAYWRIGHT_SCREENSHOT_QUALITY", 72)),
                        'url': url,
                        'user_agent': {k.lower(): v for k, v in request_headers.items()}.get('user-agent', None),
                        'proxy_username': self.proxy.get('username', '') if self.proxy else False,
                        'proxy_password': self.proxy.get('password', '') if self.proxy and self.proxy.get('username') else False,
                        'no_cache_list': [
                            'twitter',
                            '.pdf'
                        ],
                        # Could use https://github.com/easylist/easylist here, or install a plugin
                        'block_url_list': [
                            'adnxs.com',
                            'analytics.twitter.com',
                            'doubleclick.net',
                            'google-analytics.com',
                            'googletagmanager',
                            'trustpilot.com'
                        ]
                    }
                },
                # @todo /function needs adding ws:// to http:// rebuild this
                url=browserless_function_url+f"{amp}--disable-features=AudioServiceOutOfProcess&dumpio=true&--disable-remote-fonts",
                timeout=wait_browserless_seconds)

        except ReadTimeout:
            raise PageUnloadable(url=url, status_code=None, message=f"No response from browserless in {wait_browserless_seconds}s")
        except ConnectTimeout:
            raise PageUnloadable(url=url, status_code=None, message=f"Timed out connecting to browserless, retrying..")
        else:
            # 200 Here means that the communication to browserless worked only, not the page state
            try:
                x = response.json()
            except Exception as e:
                raise PageUnloadable(url=url, message="Error reading JSON response from browserless")

            try:
                self.status_code = response.status_code
            except Exception as e:
                raise PageUnloadable(url=url, message="Error reading status_code code response from browserless")

            self.headers = x.get('headers')

            if self.status_code != 200 and not ignore_status_codes:
                raise Non200ErrorCodeReceived(url=url, status_code=self.status_code, page_html=x.get('content',''))

            if self.status_code == 200:
                import base64

                if not x.get('screenshot'):
                    # https://github.com/puppeteer/puppeteer/blob/v1.0.0/docs/troubleshooting.md#tips
                    # https://github.com/puppeteer/puppeteer/issues/1834
                    # https://github.com/puppeteer/puppeteer/issues/1834#issuecomment-381047051
                    # Check your memory is shared and big enough
                    raise ScreenshotUnavailable(url=url, status_code=None)

                if not x.get('content', '').strip():
                    raise EmptyReply(url=url, status_code=None)

                self.content = x.get('content')
                self.instock_data = x.get('instock_data')
                self.screenshot = base64.b64decode(x.get('screenshot'))
                self.xpath_data = x.get('xpath_data')
            else:
                # Some other error from browserless
                raise PageUnloadable(url=url, status_code=None, message=response.content.decode('utf-8'))

    def run(self,
            url,
            timeout,
            request_headers,
            request_body,
            request_method,
            ignore_status_codes=False,
            current_include_filters=None,
            is_binary=False):


        # For now, USE_EXPERIMENTAL_PUPPETEER_FETCH is not supported by watches with BrowserSteps (for now!)
        # browser_connection_is_custom doesnt work with puppeteer style fetch (use playwright native too in this case)
        if not self.browser_connection_is_custom and not self.browser_steps and os.getenv('USE_EXPERIMENTAL_PUPPETEER_FETCH'):
            if strtobool(os.getenv('USE_EXPERIMENTAL_PUPPETEER_FETCH')):
                # Temporary backup solution until we rewrite the playwright code
                return self.run_fetch_browserless_puppeteer(
                    url,
                    timeout,
                    request_headers,
                    request_body,
                    request_method,
                    ignore_status_codes,
                    current_include_filters,
                    is_binary)

        from playwright.sync_api import sync_playwright
        import playwright._impl._errors

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
                user_agent={k.lower(): v for k, v in request_headers.items()}.get('user-agent', None),
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

            # Listen for all console events and handle errors
            self.page.on("console", lambda msg: print(f"Playwright console: Watch URL: {url} {msg.type}: {msg.text} {msg.args}"))

            # Re-use as much code from browser steps as possible so its the same
            from changedetectionio.blueprint.browser_steps.browser_steps import steppable_browser_interface
            browsersteps_interface = steppable_browser_interface()
            browsersteps_interface.page = self.page

            response = browsersteps_interface.action_goto_url(value=url)
            self.headers = response.all_headers()

            if response is None:
                context.close()
                browser.close()
                logger.debug("Content Fetcher > Response object was none")
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
                logger.critical(f"Response from browserless/playwright did not have a status_code! Response follows.")
                logger.critical(response)
                raise PageUnloadable(url=url, status_code=None, message=str(e))

            if self.status_code != 200 and not ignore_status_codes:

                screenshot=self.page.screenshot(type='jpeg', full_page=True,
                                     quality=int(os.getenv("PLAYWRIGHT_SCREENSHOT_QUALITY", 72)))

                raise Non200ErrorCodeReceived(url=url, status_code=self.status_code, screenshot=screenshot)

            if len(self.page.content().strip()) == 0:
                context.close()
                browser.close()
                logger.debug("Content Fetcher > Content was empty")
                raise EmptyReply(url=url, status_code=response.status)

            # Run Browser Steps here
            if self.browser_steps_get_valid_steps():
                self.iterate_browser_steps()
                
            self.page.wait_for_timeout(extra_wait * 1000)

            # So we can find an element on the page where its selector was entered manually (maybe not xPath etc)
            if current_include_filters is not None:
                self.page.evaluate("var include_filters={}".format(json.dumps(current_include_filters)))
            else:
                self.page.evaluate("var include_filters=''")

            self.xpath_data = self.page.evaluate(
                "async () => {" + self.xpath_element_js.replace('%ELEMENTS%', visualselector_xpath_selectors) + "}")
            self.instock_data = self.page.evaluate("async () => {" + self.instock_data_js + "}")

            self.content = self.page.content()
            # Bug 3 in Playwright screenshot handling
            # Some bug where it gives the wrong screenshot size, but making a request with the clip set first seems to solve it
            # JPEG is better here because the screenshots can be very very large

            # Screenshots also travel via the ws:// (websocket) meaning that the binary data is base64 encoded
            # which will significantly increase the IO size between the server and client, it's recommended to use the lowest
            # acceptable screenshot quality here
            try:
                # The actual screenshot
                self.screenshot = self.page.screenshot(type='jpeg', full_page=True,
                                                       quality=int(os.getenv("PLAYWRIGHT_SCREENSHOT_QUALITY", 72)))
            except Exception as e:
                context.close()
                browser.close()
                raise ScreenshotUnavailable(url=url, status_code=response.status_code)

            context.close()
            browser.close()


class base_html_webdriver(Fetcher):
    if os.getenv("WEBDRIVER_URL"):
        fetcher_description = "WebDriver Chrome/Javascript via '{}'".format(os.getenv("WEBDRIVER_URL"))
    else:
        fetcher_description = "WebDriver Chrome/Javascript"

    # Configs for Proxy setup
    # In the ENV vars, is prefixed with "webdriver_", so it is for example "webdriver_sslProxy"
    selenium_proxy_settings_mappings = ['proxyType', 'ftpProxy', 'httpProxy', 'noProxy',
                                        'proxyAutoconfigUrl', 'sslProxy', 'autodetect',
                                        'socksProxy', 'socksVersion', 'socksUsername', 'socksPassword']
    proxy = None

    def __init__(self, proxy_override=None, custom_browser_connection_url=None):
        super().__init__()
        from selenium.webdriver.common.proxy import Proxy as SeleniumProxy

        # .strip('"') is going to save someone a lot of time when they accidently wrap the env value
        if not custom_browser_connection_url:
            self.browser_connection_url = os.getenv("WEBDRIVER_URL", 'http://browser-chrome:4444/wd/hub').strip('"')
        else:
            self.browser_connection_is_custom = True
            self.browser_connection_url = custom_browser_connection_url

        # If any proxy settings are enabled, then we should setup the proxy object
        proxy_args = {}
        for k in self.selenium_proxy_settings_mappings:
            v = os.getenv('webdriver_' + k, False)
            if v:
                proxy_args[k] = v.strip('"')

        # Map back standard HTTP_ and HTTPS_PROXY to webDriver httpProxy/sslProxy
        if not proxy_args.get('webdriver_httpProxy') and self.system_http_proxy:
            proxy_args['httpProxy'] = self.system_http_proxy
        if not proxy_args.get('webdriver_sslProxy') and self.system_https_proxy:
            proxy_args['httpsProxy'] = self.system_https_proxy

        # Allows override the proxy on a per-request basis
        if proxy_override is not None:
            proxy_args['httpProxy'] = proxy_override

        if proxy_args:
            self.proxy = SeleniumProxy(raw=proxy_args)

    def run(self,
            url,
            timeout,
            request_headers,
            request_body,
            request_method,
            ignore_status_codes=False,
            current_include_filters=None,
            is_binary=False):

        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        from selenium.common.exceptions import WebDriverException
        # request_body, request_method unused for now, until some magic in the future happens.

        options = ChromeOptions()
        if self.proxy:
            options.proxy = self.proxy

        self.driver = webdriver.Remote(
            command_executor=self.browser_connection_url,
            options=options)

        try:
            self.driver.get(url)
        except WebDriverException as e:
            # Be sure we close the session window
            self.quit()
            raise

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

    # Does the connection to the webdriver work? run a test connection.
    def is_ready(self):
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options as ChromeOptions

        self.driver = webdriver.Remote(
            command_executor=self.command_executor,
            options=ChromeOptions())

        # driver.quit() seems to cause better exceptions
        self.quit()
        return True

    def quit(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                logger.debug(f"Content Fetcher > Exception in chrome shutdown/quit {str(e)}")


# "html_requests" is listed as the default fetcher in store.py!
class html_requests(Fetcher):
    fetcher_description = "Basic fast Plaintext/HTTP Client"

    def __init__(self, proxy_override=None, custom_browser_connection_url=None):
        super().__init__()
        self.proxy_override = proxy_override
        # browser_connection_url is none because its always 'launched locally'

    def run(self,
            url,
            timeout,
            request_headers,
            request_body,
            request_method,
            ignore_status_codes=False,
            current_include_filters=None,
            is_binary=False):

        if self.browser_steps_get_valid_steps():
            raise BrowserStepsInUnsupportedFetcher(url=url)

        # Make requests use a more modern looking user-agent
        if not {k.lower(): v for k, v in request_headers.items()}.get('user-agent', None):
            request_headers['User-Agent'] = os.getenv("DEFAULT_SETTINGS_HEADERS_USERAGENT",
                                                      'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.66 Safari/537.36')

        proxies = {}

        # Allows override the proxy on a per-request basis

        # https://requests.readthedocs.io/en/latest/user/advanced/#socks
        # Should also work with `socks5://user:pass@host:port` type syntax.

        if self.proxy_override:
            proxies = {'http': self.proxy_override, 'https': self.proxy_override, 'ftp': self.proxy_override}
        else:
            if self.system_http_proxy:
                proxies['http'] = self.system_http_proxy
            if self.system_https_proxy:
                proxies['https'] = self.system_https_proxy

        r = requests.request(method=request_method,
                             data=request_body,
                             url=url,
                             headers=request_headers,
                             timeout=timeout,
                             proxies=proxies,
                             verify=False)

        # If the response did not tell us what encoding format to expect, Then use chardet to override what `requests` thinks.
        # For example - some sites don't tell us it's utf-8, but return utf-8 content
        # This seems to not occur when using webdriver/selenium, it seems to detect the text encoding more reliably.
        # https://github.com/psf/requests/issues/1604 good info about requests encoding detection
        if not is_binary:
            # Don't run this for PDF (and requests identified as binary) takes a _long_ time
            if not r.headers.get('content-type') or not 'charset=' in r.headers.get('content-type'):
                encoding = chardet.detect(r.content)['encoding']
                if encoding:
                    r.encoding = encoding

        self.headers = r.headers

        if not r.content or not len(r.content):
            raise EmptyReply(url=url, status_code=r.status_code)

        # @todo test this
        # @todo maybe you really want to test zero-byte return pages?
        if r.status_code != 200 and not ignore_status_codes:
            # maybe check with content works?
            raise Non200ErrorCodeReceived(url=url, status_code=r.status_code, page_html=r.text)

        self.status_code = r.status_code
        if is_binary:
            # Binary files just return their checksum until we add something smarter
            self.content = hashlib.md5(r.content).hexdigest()
        else:
            self.content = r.text


        self.raw_content = r.content


# Decide which is the 'real' HTML webdriver, this is more a system wide config
# rather than site-specific.
use_playwright_as_chrome_fetcher = os.getenv('PLAYWRIGHT_DRIVER_URL', False)
if use_playwright_as_chrome_fetcher:
    html_webdriver = base_html_playwright
else:
    html_webdriver = base_html_webdriver
