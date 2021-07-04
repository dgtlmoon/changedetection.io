import time
from abc import ABC, abstractmethod

class EmptyReply(Exception):
    pass

class Fetcher():
    error = None
    status_code = None
    content = None # Should be bytes?

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

class html_webdriver(Fetcher):

    def run(self, url, timeout, request_headers):
        from selenium import webdriver
        from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
        from selenium.common.exceptions import WebDriverException

        # check env for WEBDRIVER_URL
        driver = webdriver.Remote(
            command_executor='http://browser-chrome:4444/wd/hub',
            desired_capabilities=DesiredCapabilities.CHROME)

        try:
            driver.get(url)
        except WebDriverException as e:
            # Be sure we close the session window
            driver.quit()
            raise



        # @todo - how to check this? is it possible?
        self.status_code = 200

        time.sleep(5)  # Let the user actually see something!
        self.content = driver.page_source

        driver.quit()


class html_requests(Fetcher):

    def run(self, url, timeout, request_headers):
        import requests
        try:
            r = requests.get(url,
                             headers=request_headers,
                             timeout=timeout,
                             verify=False)

            html = r.text

        # Usually from networkIO/requests level
        except (
                requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout,
                requests.exceptions.MissingSchema) as e:
            self.error = str(e)
            return None

        except Exception as e:
            self.error = "Other exception" + str(e)
            return None

        # @todo test this
        if not r or not html or not len(html):
            raise EmptyReply(url)

        self.status_code = r.status_code
        self.content = html

