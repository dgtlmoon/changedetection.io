from abc import ABC, abstractmethod
import chardet
import os
from selenium import webdriver
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.webdriver.common.proxy import Proxy as SeleniumProxy
from selenium.common.exceptions import WebDriverException
import requests
import time
import json
import urllib3.exceptions


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

    fetcher_description ="No description"
    xpath_element_js="""               
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
            ignore_status_codes=False):
        # Should set self.error, self.status_code and self.content
        pass

    @abstractmethod
    def quit(self):
        return

    @abstractmethod
    def screenshot(self):
        return

    @abstractmethod
    def get_last_status_code(self):
        return self.status_code

    @abstractmethod
    # Return true/false if this checker is ready to run, in the case it needs todo some special config check etc
    def is_ready(self):
        return True

    @abstractmethod
    def get_xpath_data(self, current_css_xpath_filter):
        return None


#   Maybe for the future, each fetcher provides its own diff output, could be used for text, image
#   the current one would return javascript output (as we use JS to generate the diff)
#
#   Returns tuple(mime_type, stream)
#    @abstractmethod
#    def return_diff(self, stream_a, stream_b):
#        return

def available_fetchers():
        import inspect
        from changedetectionio import content_fetcher
        p=[]
        for name, obj in inspect.getmembers(content_fetcher):
            if inspect.isclass(obj):
                # @todo html_ is maybe better as fetcher_ or something
                # In this case, make sure to edit the default one in store.py and fetch_site_status.py
                if "html_" in name:
                    t=tuple([name,obj.fetcher_description])
                    p.append(t)

        return p

class html_webdriver(Fetcher):
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



    proxy=None

    def __init__(self):
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
            ignore_status_codes=False):

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

        # @todo - how to check this? is it possible?
        self.status_code = 200
        # @todo somehow we should try to get this working for WebDriver
        # raise EmptyReply(url=url, status_code=r.status_code)

        # @todo - dom wait loaded?
        time.sleep(int(os.getenv("WEBDRIVER_DELAY_BEFORE_CONTENT_READY", 5)))
        self.content = self.driver.page_source
        self.headers = {}

    def screenshot(self):
        return self.driver.get_screenshot_as_png()

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

    def get_xpath_data(self, current_css_xpath_filter):

        # lazy quoting, probably going to be bad later.
        css_filter = current_css_xpath_filter.replace('"', '\\"')
        css_filter = css_filter.replace('\'', '\\\'')
        info = self.driver.execute_script("var css_filter='{}';".format(css_filter)+self.xpath_element_js)
        return info


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
            ignore_status_codes=False):

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

