#!/usr/bin/python3

from abc import abstractmethod
import os
import time
import logging
from playwright.async_api import async_playwright
from playwright.sync_api import sync_playwright
import playwright._impl._api_types
from playwright._impl._api_types import Error, TimeoutError
import asyncio
from playwright.async_api import async_playwright


class BrowserStepBase():

    page = None # instance of

    # Blank step
    def choose_one(self, step):
        return

    @abstractmethod
    def enter_text_in_field(self, step):
        return

    @abstractmethod
    def wait_for_text(self, step):
        return

    @abstractmethod
    def wait_for_seconds(self, step):
        return

    @abstractmethod
    def click_button(self, step):
        return

    @abstractmethod
    def click_button_containing_text(self, step):
        return


# Good reference - https://playwright.dev/python/docs/input
#                  https://pythonmana.com/2021/12/202112162236307035.html
class browsersteps_playwright(BrowserStepBase):
    def enter_text_in_field(self, step):
        self.page.fill(step['selector'], step['optional_value'])
        return

    def wait_for_text(self, step):
        return

    def wait_for_seconds(self, step):
        self.page.wait_for_timeout(int(step['optional_value']) * 1000)
        return

    def click_button(self, step):
        self.page.click(step['selector'])
        return

    def click_button_containing_text(self, step):
        self.page.click("text="+step['optional_value'])
        return

    def select_by_label(self, step):
        self.page.select_option(step['selector'], label=step['optional_value'])
        return

class browsersteps_selenium(BrowserStepBase):
    def enter_text_in_field(self, step):
        return

    def wait_for_text(self, step):
        return

    def wait_for_seconds(self, step):
        return

    def click_button(self, step):
        return

    def click_button_containing_text(self, step):
        return

# Responsible for maintaining a live 'context' with browserless
# @todo - how long do contexts live for anyway?
class browsersteps_live_ui():

    context = None
    page = None
    render_extra_delay = 1
    # bump and kill this if idle after X sec
    age_start = 0

    command_executor = "ws://127.0.0.1:3000"
    browser_type = os.getenv("PLAYWRIGHT_BROWSER_TYPE", 'chromium').strip('"')

    def __init__(self):
        self.age_start = time.time()
        if self.context is None:
            self.connect()


    # Connect and setup a new context
    def connect(self):
        logging.debug("browser_steps.py connecting")
        from playwright.sync_api import sync_playwright
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.connect_over_cdp(self.command_executor, timeout=60000)

        self.context = self.browser.new_context(
            # @todo
            #                user_agent=request_headers['User-Agent'] if request_headers.get('User-Agent') else 'Mozilla/5.0',
            #               proxy=self.proxy,
            # This is needed to enable JavaScript execution on GitHub and others
            bypass_csp=True,
            # Should never be needed
            accept_downloads=False
        )

        self.page = self.context.new_page()
        self.page.set_default_navigation_timeout(90000)
        self.page.set_default_timeout(90000)

    def action_goto_url(self, url):
        with self.page.expect_navigation():
            response = self.page.goto(url, wait_until='load')
        # Wait_until = commit
        # - `'commit'` - consider operation to be finished when network response is received and the document started loading.
        # Better to not use any smarts from Playwright and just wait an arbitrary number of seconds
        # This seemed to solve nearly all 'TimeoutErrors'
        extra_wait = int(os.getenv("WEBDRIVER_DELAY_BEFORE_CONTENT_READY", 5))
        self.page.wait_for_timeout(extra_wait * 1000)


    def get_current_state(self):
        """Return the screenshot and interactive elements mapping, generally always called after action_()"""

        from . import content_fetcher
        # Quality set to 1 because it's not used, just used as a work-around for a bug, no need to change this.
        self.page.screenshot(type='jpeg', clip={'x': 1.0, 'y': 1.0, 'width': 1280, 'height': 1024}, quality=1)
        # The actual screenshot
        screenshot = self.page.screenshot(type='jpeg', full_page=True, quality=int(os.getenv("PLAYWRIGHT_SCREENSHOT_QUALITY", 72)))

        self.page.evaluate("var css_filter=''")
        xpath_data = self.page.evaluate("async () => {" + content_fetcher.xpath_element_js.replace('%ELEMENTS%','input, button, textarea, img, a, span, div') + "}")

        return (screenshot, xpath_data)
