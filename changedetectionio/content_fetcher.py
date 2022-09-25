from abc import ABC, abstractmethod
import chardet
import json
import os
import requests
import time
import sys


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


class JSActionExceptions(Exception):
    def __init__(self, status_code, url, screenshot, message=''):
        self.status_code = status_code
        self.url = url
        self.screenshot = screenshot
        self.message = message
        return

class PageUnloadable(Exception):
    def __init__(self, status_code, url, screenshot=False, message=False):
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

    fetcher_description = "No description"
    webdriver_js_execute_code = None
    xpath_element_js = """               
                // Include the getXpath script directly, easier than fetching
                !function(e,n){"object"==typeof exports&&"undefined"!=typeof module?module.exports=n():"function"==typeof define&&define.amd?define(n):(e=e||self).getXPath=n()}(this,function(){return function(e){var n=e;if(n&&n.id)return'//*[@id="'+n.id+'"]';for(var o=[];n&&Node.ELEMENT_NODE===n.nodeType;){for(var i=0,r=!1,d=n.previousSibling;d;)d.nodeType!==Node.DOCUMENT_TYPE_NODE&&d.nodeName===n.nodeName&&i++,d=d.previousSibling;for(d=n.nextSibling;d;){if(d.nodeName===n.nodeName){r=!0;break}d=d.nextSibling}o.push((n.prefix?n.prefix+":":"")+n.localName+(i||r?"["+(i+1)+"]":"")),n=n.parentNode}return o.length?"/"+o.reverse().join("/"):""}});


                const findUpTag = (el) => {
                  let r = el
                  chained_css = [];
                  depth=0;
            
                // Strategy 1: Keep going up until we hit an ID tag, imagine it's like  #list-widget div h4
                  while (r.parentNode) {
                    if(depth==5) {
                      break;
                    }
                    if('' !==r.id) {
                      chained_css.unshift("#"+CSS.escape(r.id));
                      final_selector= chained_css.join(' > ');
                      // Be sure theres only one, some sites have multiples of the same ID tag :-(
                      if (window.document.querySelectorAll(final_selector).length ==1 ) {
                        return final_selector;
                        }
                      return null;
                    } else {
                      chained_css.unshift(r.tagName.toLowerCase());
                    }
                    r=r.parentNode;
                    depth+=1;
                  }
                  return null;
                }


                // @todo - if it's SVG or IMG, go into image diff mode
                var elements = window.document.querySelectorAll("div,span,form,table,tbody,tr,td,a,p,ul,li,h1,h2,h3,h4, header, footer, section, article, aside, details, main, nav, section, summary");
                var size_pos=[];
                // after page fetch, inject this JS
                // build a map of all elements and their positions (maybe that only include text?)
                var bbox;
                for (var i = 0; i < elements.length; i++) {   
                 bbox = elements[i].getBoundingClientRect();

                 // forget really small ones
                 if (bbox['width'] <20 && bbox['height'] < 20 ) {
                   continue;
                 }

                 // @todo the getXpath kind of sucks, it doesnt know when there is for example just one ID sometimes
                 // it should not traverse when we know we can anchor off just an ID one level up etc..
                 // maybe, get current class or id, keep traversing up looking for only class or id until there is just one match 

                 // 1st primitive - if it has class, try joining it all and select, if theres only one.. well thats us.
                 xpath_result=false;
                 
                 try {
                   var d= findUpTag(elements[i]);
                   if (d) {
                     xpath_result =d;
                   }                
                 } catch (e) {
                   console.log(e);
                 }
                 
                 // You could swap it and default to getXpath and then try the smarter one
                 // default back to the less intelligent one
                 if (!xpath_result) {
                    try {
                       // I've seen on FB and eBay that this doesnt work
                       // ReferenceError: getXPath is not defined at eval (eval at evaluate (:152:29), <anonymous>:67:20) at UtilityScript.evaluate (<anonymous>:159:18) at UtilityScript.<anonymous> (<anonymous>:1:44)
                       xpath_result = getXPath(elements[i]);
                     } catch (e) {
                       console.log(e);
                       continue;
                     }            
                 }
                 
                 if(window.getComputedStyle(elements[i]).visibility === "hidden") {
                   continue;
                 }

                 size_pos.push({
                   xpath: xpath_result,
                   width: Math.round(bbox['width']), 
                   height: Math.round(bbox['height']), 
                   left: Math.floor(bbox['left']), 
                   top: Math.floor(bbox['top']), 
                   childCount: elements[i].childElementCount
                 });                 
                }


                // inject the current one set in the css_filter, which may be a CSS rule
                // used for displaying the current one in VisualSelector, where its not one we generated.
                if (css_filter.length) {
                   q=false;                   
                   try {
                       // is it xpath?
                       if (css_filter.startsWith('/') || css_filter.startsWith('xpath:')) {
                         q=document.evaluate(css_filter.replace('xpath:',''), document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                       } else {
                         q=document.querySelector(css_filter);
                       }                       
                   } catch (e) {
                    // Maybe catch DOMException and alert? 
                     console.log(e);                       
                   }
                   bbox=false;
                   if(q) {
                     bbox = q.getBoundingClientRect();
                   }
                                   
                   if (bbox && bbox['width'] >0 && bbox['height']>0) {                       
                       size_pos.push({
                           xpath: css_filter,
                           width: bbox['width'], 
                           height: bbox['height'],
                           left: bbox['left'],
                           top: bbox['top'],
                           childCount: q.childElementCount
                         });
                     }
                }
                // Window.width required for proper scaling in the frontend
                return {'size_pos':size_pos, 'browser_width': window.innerWidth};
    """
    xpath_data = None

    # Will be needed in the future by the VisualSelector, always get this where possible.
    screenshot = False
    system_http_proxy = os.getenv('HTTP_PROXY')
    system_https_proxy = os.getenv('HTTPS_PROXY')

    # Time ONTOP of the system defined env minimum time
    render_extract_delay = 0

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
            current_css_filter=None):
        # Should set self.error, self.status_code and self.content
        pass

    @abstractmethod
    def quit(self):
        return

    @abstractmethod
    def get_last_status_code(self):
        return self.status_code

    @abstractmethod
    # Return true/false if this checker is ready to run, in the case it needs todo some special config check etc
    def is_ready(self):
        return True


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
            # https://playwright.dev/docs/network#http-proxy
            from urllib.parse import urlparse
            parsed = urlparse(proxy_override)
            proxy_url = "{}://{}:{}".format(parsed.scheme, parsed.hostname, parsed.port)
            self.proxy = {'server': proxy_url}
            if parsed.username:
                self.proxy['username'] = parsed.username
            if parsed.password:
                self.proxy['password'] = parsed.password

    def run(self,
            url,
            timeout,
            request_headers,
            request_body,
            request_method,
            ignore_status_codes=False,
            current_css_filter=None):

        from playwright.sync_api import sync_playwright
        import playwright._impl._api_types
        from playwright._impl._api_types import Error, TimeoutError
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
                # Should never be needed
                accept_downloads=False
            )

            if len(request_headers):
                context.set_extra_http_headers(request_headers)

            page = context.new_page()
            try:
                page.set_default_navigation_timeout(90000)
                page.set_default_timeout(90000)

                # Listen for all console events and handle errors
                page.on("console", lambda msg: print(f"Playwright console: Watch URL: {url} {msg.type}: {msg.text} {msg.args}"))

                # Bug - never set viewport size BEFORE page.goto

                # Waits for the next navigation. Using Python context manager
                # prevents a race condition between clicking and waiting for a navigation.
                with page.expect_navigation():
                    response = page.goto(url, wait_until='load')


            except playwright._impl._api_types.TimeoutError as e:
                context.close()
                browser.close()
                # This can be ok, we will try to grab what we could retrieve
                pass

            except Exception as e:
                print("other exception when page.goto")
                print(str(e))
                context.close()
                browser.close()
                raise PageUnloadable(url=url, status_code=None, message=e.message)

            if response is None:
                context.close()
                browser.close()
                print("response object was none")
                raise EmptyReply(url=url, status_code=None)


            # Removed browser-set-size, seemed to be needed to make screenshots work reliably in older playwright versions
            # Was causing exceptions like 'waiting for page but content is changing' etc
            # https://www.browserstack.com/docs/automate/playwright/change-browser-window-size 1280x720 should be the default
                        
            extra_wait = int(os.getenv("WEBDRIVER_DELAY_BEFORE_CONTENT_READY", 5)) + self.render_extract_delay
            time.sleep(extra_wait)

            if self.webdriver_js_execute_code is not None:
                try:
                    page.evaluate(self.webdriver_js_execute_code)
                except Exception as e:
                    # Is it possible to get a screenshot?
                    error_screenshot = False
                    try:
                        page.screenshot(type='jpeg',
                                        clip={'x': 1.0, 'y': 1.0, 'width': 1280, 'height': 1024},
                                        quality=1)

                        # The actual screenshot
                        error_screenshot = page.screenshot(type='jpeg',
                                                           full_page=True,
                                                           quality=int(os.getenv("PLAYWRIGHT_SCREENSHOT_QUALITY", 72)))
                    except Exception as s:
                        pass

                    raise JSActionExceptions(status_code=response.status, screenshot=error_screenshot, message=str(e), url=url)

                else:
                    # JS eval was run, now we also wait some time if possible to let the page settle
                    if self.render_extract_delay:
                        page.wait_for_timeout(self.render_extract_delay * 1000)

            page.wait_for_timeout(500)

            self.content = page.content()
            self.status_code = response.status
            self.headers = response.all_headers()

            if current_css_filter is not None:
                page.evaluate("var css_filter={}".format(json.dumps(current_css_filter)))
            else:
                page.evaluate("var css_filter=''")

            self.xpath_data = page.evaluate("async () => {" + self.xpath_element_js + "}")

            # Bug 3 in Playwright screenshot handling
            # Some bug where it gives the wrong screenshot size, but making a request with the clip set first seems to solve it
            # JPEG is better here because the screenshots can be very very large

            # Screenshots also travel via the ws:// (websocket) meaning that the binary data is base64 encoded
            # which will significantly increase the IO size between the server and client, it's recommended to use the lowest
            # acceptable screenshot quality here
            try:
                # Quality set to 1 because it's not used, just used as a work-around for a bug, no need to change this.
                page.screenshot(type='jpeg', clip={'x': 1.0, 'y': 1.0, 'width': 1280, 'height': 1024}, quality=1)
                # The actual screenshot
                self.screenshot = page.screenshot(type='jpeg', full_page=True, quality=int(os.getenv("PLAYWRIGHT_SCREENSHOT_QUALITY", 72)))
            except Exception as e:
                context.close()
                browser.close()
                raise ScreenshotUnavailable(url=url, status_code=None)

            if len(self.content.strip()) == 0:
                context.close()
                browser.close()
                print("Content was empty")
                raise EmptyReply(url=url, status_code=None, screenshot=self.screenshot)

            context.close()
            browser.close()

            if not ignore_status_codes and self.status_code!=200:
                raise Non200ErrorCodeReceived(url=url, status_code=self.status_code, page_html=self.content, screenshot=self.screenshot)

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
            current_css_filter=None):

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
        from selenium.common.exceptions import WebDriverException

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
                print("Exception in chrome shutdown/quit" + str(e))


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
            current_css_filter=None):

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
        self.content = r.text
        self.headers = r.headers


# Decide which is the 'real' HTML webdriver, this is more a system wide config
# rather than site-specific.
use_playwright_as_chrome_fetcher = os.getenv('PLAYWRIGHT_DRIVER_URL', False)
if use_playwright_as_chrome_fetcher:
    html_webdriver = base_html_playwright
else:
    html_webdriver = base_html_webdriver
