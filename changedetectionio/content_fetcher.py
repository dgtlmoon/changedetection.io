from abc import ABC, abstractmethod
import chardet
import os
import requests
import time
import json
import urllib3.exceptions
import sys


class EmptyReply(Exception):
    def __init__(self, status_code, url):
        # Set this so we can use it in other parts of the app
        self.status_code = status_code
        self.url = url
        return

    pass


class Fetcher():
    error = None
    status_code = None
    content = None
    headers = None

    fetcher_description = "No description"
    xpath_element_js = """               
                // Include the getXpath script directly, easier than fetching
                !function(e,n){"object"==typeof exports&&"undefined"!=typeof module?module.exports=n():"function"==typeof define&&define.amd?define(n):(e=e||self).getXPath=n()}(this,function(){return function(e){var n=e;if(n&&n.id)return'//*[@id="'+n.id+'"]';for(var o=[];n&&Node.ELEMENT_NODE===n.nodeType;){for(var i=0,r=!1,d=n.previousSibling;d;)d.nodeType!==Node.DOCUMENT_TYPE_NODE&&d.nodeName===n.nodeName&&i++,d=d.previousSibling;for(d=n.nextSibling;d;){if(d.nodeName===n.nodeName){r=!0;break}d=d.nextSibling}o.push((n.prefix?n.prefix+":":"")+n.localName+(i||r?"["+(i+1)+"]":"")),n=n.parentNode}return o.length?"/"+o.reverse().join("/"):""}});
                //# sourceMappingURL=index.umd.js.map             


                const findUpTag = (el) => {
                  let r = el
                  chained_css = [];

                  while (r.parentNode) {

                    if(r.classList.length >0) {
                     // limit to just using 2 class names of each, stops from getting really huge selector strings
                      current_css='.'+Array.from(r.classList).slice(0, 2).join('.');
                      chained_css.unshift(current_css);

                      var f=chained_css.join(' ');
                      var q=document.querySelectorAll(f);
                      if(q.length==1) return current_css;
                      if(f.length >120) return null;
                    }  
                    r = r.parentNode;
                  }
                  return null;
                }


                var elements = document.getElementsByTagName("*");
                var size_pos=[];
                // after page fetch, inject this JS
                // build a map of all elements and their positions (maybe that only include text?)
                var bbox;
                for (var i = 0; i < elements.length; i++) {   
                 bbox = elements[i].getBoundingClientRect();

                 // forget reallysmall ones
                 if (bbox['width'] <10 && bbox['height'] <10 ) {
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
                   var x=1;
                 }

                 // default back to the less intelligent one
                 if (!xpath_result) {
                   xpath_result = getXPath(elements[i]);                   
                 } 

                 size_pos.push({
                   xpath: xpath_result,
                   width: bbox['width'], 
                   height: bbox['height'],
                   left: bbox['left'],
                   top: bbox['top'],
                   childCount: elements[i].childElementCount
                 });                 
                }


                // inject the current one set in the css_filter, which may be a CSS rule
                // used for displaying the current one in VisualSelector, where its not one we generated.
                if (css_filter.length) {
                   // is it xpath?
                   if (css_filter.startsWith('/') ) {
                     q=document.evaluate(css_filter, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                   } else {
                     q=document.querySelector(css_filter);
                   }
                   if (q) {
                       bbox = q.getBoundingClientRect();
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

                return size_pos;
    """
    xpath_data = None

    # Will be needed in the future by the VisualSelector, always get this where possible.
    screenshot = False

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

    #    try:
    #        from playwright.sync_api import sync_playwright
    #    except ModuleNotFoundError:
    #        fetcher_enabled = False

    browser_type = ''
    command_executor = ''

    # Configs for Proxy setup
    # In the ENV vars, is prefixed with "playwright_proxy_", so it is for example "playwright_proxy_server"
    playwright_proxy_settings_mappings = ['server', 'bypass', 'username', 'password']

    proxy = None

    def __init__(self):
        # .strip('"') is going to save someone a lot of time when they accidently wrap the env value
        self.browser_type = os.getenv("PLAYWRIGHT_BROWSER_TYPE", 'chromium').strip('"')
        self.command_executor = os.getenv(
            "PLAYWRIGHT_DRIVER_URL",
            'ws://playwright-chrome:3000/playwright'
        ).strip('"')

        # If any proxy settings are enabled, then we should setup the proxy object
        proxy_args = {}
        for k in self.playwright_proxy_settings_mappings:
            v = os.getenv('playwright_proxy_' + k, False)
            if v:
                proxy_args[k] = v.strip('"')

        if proxy_args:
            self.proxy = proxy_args

    def run(self,
            url,
            timeout,
            request_headers,
            request_body,
            request_method,
            ignore_status_codes=False,
            current_css_filter=None):

        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser_type = getattr(p, self.browser_type)

            # Seemed to cause a connection Exception even tho I can see it connect
            # self.browser = browser_type.connect(self.command_executor, timeout=timeout*1000)
            browser = browser_type.connect_over_cdp(self.command_executor, timeout=timeout * 1000)

            # Set user agent to prevent Cloudflare from blocking the browser
            context = browser.new_context(
                user_agent="Mozilla/5.0",
                proxy=self.proxy
            )
            page = context.new_page()
            response = page.goto(url, timeout=timeout * 1000)
            # set size after visiting page, otherwise it wont work (seems to default to 800x)
            page.set_viewport_size({"width": 1280, "height": 1024})

            extra_wait = int(os.getenv("WEBDRIVER_DELAY_BEFORE_CONTENT_READY", 5))
            page.wait_for_timeout(extra_wait * 1000)

            if response is None:
                raise EmptyReply(url=url, status_code=None)

            self.status_code = response.status
            self.content = page.content()
            self.headers = response.all_headers()

            if current_css_filter is not None:
                page.evaluate("var css_filter='{}'".format(current_css_filter))
            else:
                page.evaluate("var css_filter=''")

            self.xpath_data = page.evaluate("async () => {" + self.xpath_element_js + "}")
            # Some bug where it gives the wrong screenshot size, but making a request with the clip set first seems to solve it
            # JPEG is better here because the screenshots can be very very large
            page.screenshot(type='jpeg', clip={'x': 1.0, 'y': 1.0, 'width': 1280, 'height': 1024})
            self.screenshot = page.screenshot(type='jpeg', full_page=True, quality=92)
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

    def __init__(self):
        from selenium.webdriver.common.proxy import Proxy as SeleniumProxy

        # .strip('"') is going to save someone a lot of time when they accidently wrap the env value
        self.command_executor = os.getenv("WEBDRIVER_URL", 'http://browser-chrome:4444/wd/hub').strip('"')

        # If any proxy settings are enabled, then we should setup the proxy object
        proxy_args = {}
        for k in self.selenium_proxy_settings_mappings:
            v = os.getenv('webdriver_' + k, False)
            if v:
                proxy_args[k] = v.strip('"')

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
        self.xpath_data = self.driver.execute_script("var css_filter='{}';".format(current_css_filter) + self.xpath_element_js)
        self.screenshot = self.driver.get_screenshot_as_png()

        # @todo - how to check this? is it possible?
        self.status_code = 200
        # @todo somehow we should try to get this working for WebDriver
        # raise EmptyReply(url=url, status_code=r.status_code)

        # @todo - dom wait loaded?
        self.content = self.driver.page_source
        self.headers = {}

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

    def run(self,
            url,
            timeout,
            request_headers,
            request_body,
            request_method,
            ignore_status_codes=False,
            current_css_filter=None):

        r = requests.request(method=request_method,
                             data=request_body,
                             url=url,
                             headers=request_headers,
                             timeout=timeout,
                             verify=False)

        # If the response did not tell us what encoding format to expect, Then use chardet to override what `requests` thinks.
        # For example - some sites don't tell us it's utf-8, but return utf-8 content
        # This seems to not occur when using webdriver/selenium, it seems to detect the text encoding more reliably.
        # https://github.com/psf/requests/issues/1604 good info about requests encoding detection
        if not r.headers.get('content-type') or not 'charset=' in r.headers.get('content-type'):
            encoding = chardet.detect(r.content)['encoding']
            if encoding:
                r.encoding = encoding

        # @todo test this
        # @todo maybe you really want to test zero-byte return pages?
        if (not ignore_status_codes and not r) or not r.content or not len(r.content):
            raise EmptyReply(url=url, status_code=r.status_code)

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
