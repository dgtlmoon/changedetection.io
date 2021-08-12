import os
import time
from abc import ABC, abstractmethod
from selenium import webdriver
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.common.exceptions import WebDriverException
import urllib3.exceptions


class EmptyReply(Exception):
    pass

class Fetcher():
    error = None
    status_code = None
    content = None # Should be bytes?

    fetcher_description ="No description"

    @abstractmethod
    def get_error(self):
        return self.error

    @abstractmethod
    def run(self, url, timeout, request_headers):
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
        from backend import content_fetcher
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
    fetcher_description = "WebDriver Chrome/Javascript"
    command_executor = ''

    def __init__(self):
        self.command_executor = os.getenv("WEBDRIVER_URL",'http://browser-chrome:4444/wd/hub')

    def run(self, url, timeout, request_headers):

        # check env for WEBDRIVER_URL
        driver = webdriver.Remote(
            command_executor=self.command_executor,
            desired_capabilities=DesiredCapabilities.CHROME)

        try:
            driver.get(url)
        except WebDriverException as e:
            # Be sure we close the session window
            driver.quit()
            raise

        # @todo - how to check this? is it possible?
        self.status_code = 200

        # @todo - dom wait loaded?
        time.sleep(5)
        self.content = driver.page_source

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

    def run(self, url, timeout, request_headers):
        import requests

        r = requests.get(url,
                         headers=request_headers,
                         timeout=timeout,
                         verify=False)

        html = r.text


        # @todo test this
        if not r or not html or not len(html):
            raise EmptyReply(url)

        self.status_code = r.status_code
        self.content = html

