import os
import time
from abc import ABC, abstractmethod
from selenium import webdriver
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.webdriver.common.proxy import Proxy as SeleniumProxy
from selenium.common.exceptions import WebDriverException
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
    content = None # Should always be bytes.
    headers = None

    fetcher_description ="No description"

    @abstractmethod
    def get_error(self):
        return self.error

    @abstractmethod
    def run(self, url, timeout, request_headers, request_body, request_method):
        # Should set self.error, self.status_code and self.content
        pass

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

    def run(self, url, timeout, request_headers, request_body, request_method):

        # request_body, request_method unused for now, until some magic in the future happens.

        # check env for WEBDRIVER_URL
        driver = webdriver.Remote(
            command_executor=self.command_executor,
            desired_capabilities=DesiredCapabilities.CHROME,
            proxy=self.proxy)

        try:
            driver.get(url)
        except WebDriverException as e:
            # Be sure we close the session window
            driver.quit()
            raise

        # @todo - how to check this? is it possible?
        self.status_code = 200
        # @todo somehow we should try to get this working for WebDriver
        # raise EmptyReply(url=url, status_code=r.status_code)

        # @todo - dom wait loaded?
        time.sleep(int(os.getenv("WEBDRIVER_DELAY_BEFORE_CONTENT_READY", 5)))
        self.content = driver.page_source
        self.headers = {}

        driver.quit()


    def is_ready(self):
        from selenium import webdriver
        from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
        from selenium.common.exceptions import WebDriverException

        driver = webdriver.Remote(
            command_executor=self.command_executor,
            desired_capabilities=DesiredCapabilities.CHROME)

        # driver.quit() seems to cause better exceptions
        driver.quit()

        return True

# "html_requests" is listed as the default fetcher in store.py!
class html_requests(Fetcher):
    fetcher_description = "Basic fast Plaintext/HTTP Client"

    def run(self, url, timeout, request_headers, request_body, request_method):
        import requests

        r = requests.request(method=request_method,
                         data=request_body,
                         url=url,
                         headers=request_headers,
                         timeout=timeout,
                         verify=False)

        # https://stackoverflow.com/questions/44203397/python-requests-get-returns-improperly-decoded-text-instead-of-utf-8
        # Return bytes here
        html = r.text

        # @todo test this
        # @todo maybe you really want to test zero-byte return pages?
        if not r or not html or not len(html):
            raise EmptyReply(url=url, status_code=r.status_code)

        self.status_code = r.status_code
        self.content = html
        self.headers = r.headers

