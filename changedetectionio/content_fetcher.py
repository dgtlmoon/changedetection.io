import hashlib
from abc import abstractmethod
import chardet
import json
import logging
import os
import requests
import sys
import time

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

class BrowserStepsStepTimout(Exception):
    def __init__(self, step_n):
        self.step_n = step_n
        return


class PageUnloadable(Exception):
    def __init__(self, status_code, url, message, screenshot=False):
        # Set this so we can use it in other parts of the app
        self.status_code = status_code
        self.url = url
        self.screenshot = screenshot
        self.message = message
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
    def __init__(self, status_code, url, screenshot=None):
        # Set this so we can use it in other parts of the app
        self.status_code = status_code
        self.url = url
        self.screenshot = screenshot
        return

class Fetcher():
    error = None
    status_code = None
    content = None
    headers = None
    browser_steps = None
    browser_steps_screenshot_path = None

    fetcher_description = "No description"
    webdriver_js_execute_code = None
    xpath_element_js = ""

    xpath_data = None

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

    def iterate_browser_steps(self):
        from changedetectionio.blueprint.browser_steps.browser_steps import steppable_browser_interface
        from playwright._impl._api_types import TimeoutError
        from jinja2 import Environment
        jinja2_env = Environment(extensions=['jinja2_time.TimeExtension'])

        step_n = 0

        if self.browser_steps is not None and len(self.browser_steps):
            interface = steppable_browser_interface()
            interface.page = self.page

            valid_steps = filter(lambda s: (s['operation'] and len(s['operation']) and s['operation'] != 'Choose one' and s['operation'] != 'Goto site'), self.browser_steps)

            for step in valid_steps:
                step_n += 1
                print(">> Iterating check - browser Step n {} - {}...".format(step_n, step['operation']))
                self.screenshot_step("before-"+str(step_n))
                self.save_step_html("before-"+str(step_n))
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
                except TimeoutError:
                    # Stop processing here
                    raise BrowserStepsStepTimout(step_n=step_n)



    # It's always good to reset these
    def delete_browser_steps_screenshots(self):
        import glob
        if self.browser_steps_screenshot_path is not None:
            dest = os.path.join(self.browser_steps_screenshot_path, 'step_*.jpeg')
            files = glob.glob(dest)
            for f in files:
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

    def __init__(self, proxy_override=None):
        super().__init__()
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

        # There's a bug where we need to do it twice or it doesnt take the whole page, dont know why.
        self.page.screenshot(type='jpeg', clip={'x': 1.0, 'y': 1.0, 'width': 1280, 'height': 1024})
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
                # Can't think why we need the service workers for our use case?
                service_workers='block',
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
                raise PageUnloadable(url=url, status_code=None, message=str(e))

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
                raise PageUnloadable(url=url, status_code=None, message=str(e))

            if response is None:
                context.close()
                browser.close()
                print ("Content Fetcher > Response object was none")
                raise EmptyReply(url=url, status_code=None)

            # Bug 2(?) Set the viewport size AFTER loading the page
            self.page.set_viewport_size({"width": 1280, "height": 1024})

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
                raise EmptyReply(url=url, status_code=response.status)

            # Bug 2(?) Set the viewport size AFTER loading the page
            self.page.set_viewport_size({"width": 1280, "height": 1024})

            self.status_code = response.status
            self.content = self.page.content()
            self.headers = response.all_headers()

            # So we can find an element on the page where its selector was entered manually (maybe not xPath etc)
            if current_include_filters is not None:
                self.page.evaluate("var include_filters={}".format(json.dumps(current_include_filters)))
            else:
                self.page.evaluate("var include_filters=''")

            self.xpath_data = self.page.evaluate("async () => {" + self.xpath_element_js.replace('%ELEMENTS%', visualselector_xpath_selectors) + "}")

            # Bug 3 in Playwright screenshot handling
            # Some bug where it gives the wrong screenshot size, but making a request with the clip set first seems to solve it
            # JPEG is better here because the screenshots can be very very large

            # Screenshots also travel via the ws:// (websocket) meaning that the binary data is base64 encoded
            # which will significantly increase the IO size between the server and client, it's recommended to use the lowest
            # acceptable screenshot quality here
            try:
                # Quality set to 1 because it's not used, just used as a work-around for a bug, no need to change this.
                self.page.screenshot(type='jpeg', clip={'x': 1.0, 'y': 1.0, 'width': 1280, 'height': 1024}, quality=1)
                # The actual screenshot
                self.screenshot = self.page.screenshot(type='jpeg', full_page=True, quality=int(os.getenv("PLAYWRIGHT_SCREENSHOT_QUALITY", 72)))
            except Exception as e:
                context.close()
                browser.close()
                raise ScreenshotUnavailable(url=url, status_code=None)

            context.close()
            browser.close()

class base_html_webdriver(Fetcher):
    if os.getenv("WEBDRIVER_URL"):
        fetcher_description = "WebDriver Chrome/Javascript via '{}'".format(os.getenv("WEBDRIVER_URL"))
    else:
        fetcher_description = "WebDriver Chrome/Javascript"

    command_executor = ''

    # Configs for Proxy setup
    # In the ENV vars, is prefixed with "webdriver_", so it is for example "webdriver_sslProxy"
    selenium_proxy_settings_mappings = ['proxyType', 'ftpProxy', 'httpProxy', 'noProxy',
                                        'proxyAutoconfigUrl', 'sslProxy', 'autodetect',
                                        'socksProxy', 'socksVersion', 'socksUsername', 'socksPassword']
    proxy = None

    def __init__(self, proxy_override=None):
        super().__init__()
        from selenium.webdriver.common.proxy import Proxy as SeleniumProxy

        # .strip('"') is going to save someone a lot of time when they accidently wrap the env value
        self.command_executor = os.getenv("WEBDRIVER_URL", 'http://browser-chrome:4444/wd/hub').strip('"')

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
        from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
        from selenium.common.exceptions import WebDriverException
        # request_body, request_method unused for now, until some magic in the future happens.

        # check env for WEBDRIVER_URL
        self.driver = webdriver.Remote(
            command_executor=self.command_executor,
            desired_capabilities=DesiredCapabilities.CHROME,
            proxy=self.proxy)

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
        from selenium.webdriver.common.desired_capabilities import DesiredCapabilities

        self.driver = webdriver.Remote(
            command_executor=self.command_executor,
            desired_capabilities=DesiredCapabilities.CHROME)

        # driver.quit() seems to cause better exceptions
        self.quit()
        return True

    def quit(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                print("Content Fetcher > Exception in chrome shutdown/quit" + str(e))


# "html_requests" is listed as the default fetcher in store.py!
class html_requests(Fetcher):
    fetcher_description = "Basic fast Plaintext/HTTP Client"

    def __init__(self, proxy_override=None):
        self.proxy_override = proxy_override

    def run(self,
            url,
            timeout,
            request_headers,
            request_body,
            request_method,
            ignore_status_codes=False,
            current_include_filters=None,
            is_binary=False):

        # Make requests use a more modern looking user-agent
        if not 'User-Agent' in request_headers:
            request_headers['User-Agent'] = os.getenv("DEFAULT_SETTINGS_HEADERS_USERAGENT",
                                                      'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.66 Safari/537.36')

        proxies = {}

        # Allows override the proxy on a per-request basis
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

        self.headers = r.headers
        self.raw_content = r.content


# Decide which is the 'real' HTML webdriver, this is more a system wide config
# rather than site-specific.
use_playwright_as_chrome_fetcher = os.getenv('PLAYWRIGHT_DRIVER_URL', False)
if use_playwright_as_chrome_fetcher:
    html_webdriver = base_html_playwright
else:
    html_webdriver = base_html_webdriver
