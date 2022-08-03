#!/usr/bin/python3

from abc import abstractmethod
import os
import time
import logging
import re

# Two flags, tell the JS which of the "Selector" or "Value" field should be enabled in the front end
# 0- off, 1- on
browser_step_ui_config = {'Choose one': '0 0',
                          'Enter text in field': '1 1',
                          'Select by label': '1 1',
                          'Wait for text': '0 1',
                          'Wait for seconds': '0 1',
                          #                 'Check checkbox': '1 0',
                          #                 'Uncheck checkbox': '1 0',
                          'Click element': '1 0',
                          'Click element if exists': '1 0',
                          #                 'Click button containing text': '0 1',
                          'Click X,Y': '0 1',
                          'Press Enter': '0 0',
# weird bug, come back to it later
#                          'Press Page Up': '0 0',
#                          'Press Page Down': '0 0',
                          'Check checkbox': '1 0',
                          'Uncheck checkbox': '1 0',
                          'Extract text and use as filter': '1 0',
                          #                 'Scroll to top': '0 0',
                          #                 'Scroll to bottom': '0 0',
                          #                 'Scroll to element': '1 0',
                          # @todo
                          #                 'Switch to iFrame by index number': '0 1'
                          }

# Good reference - https://playwright.dev/python/docs/input
#                  https://pythonmana.com/2021/12/202112162236307035.html
#
# ONLY Works in Playwright because we need the fullscreen screenshot
class steppable_browser_interface():
    page = None

    # Convert and perform "Click Button" for example
    def call_action(self, action_name, selector, optional_value):

        call_action_name = re.sub('[^0-9a-zA-Z]+', '_', action_name.lower())

        # https://playwright.dev/python/docs/selectors#xpath-selectors
        if selector.startswith('/') and not selector.startswith('//'):
            selector = "xpath=" + selector

        action_handler = getattr(self, "action_" + call_action_name)
        action_handler(selector, optional_value)
        self.page.wait_for_timeout(1 * 1000)

    def action_goto_url(self, url):
        with self.page.expect_navigation():
            self.page.set_viewport_size({"width": 1280, "height": 5000})
            response = self.page.goto(url, wait_until='load')
        # Wait_until = commit
        # - `'commit'` - consider operation to be finished when network response is received and the document started loading.
        # Better to not use any smarts from Playwright and just wait an arbitrary number of seconds
        # This seemed to solve nearly all 'TimeoutErrors'
        extra_wait = int(os.getenv("WEBDRIVER_DELAY_BEFORE_CONTENT_READY", 5))
        self.page.wait_for_timeout(extra_wait * 1000)

    def action_enter_text_in_field(self, selector, value):
        if not len(selector.strip()):
            return
        self.page.fill(selector, value, timeout=5 * 1000)

    def action_click_element(self, selector, value):
        if not len(selector.strip()):
            return
        self.page.click(selector, timeout=5 * 1000)

    def action_click_element_if_exists(self, selector, value):
        if not len(selector.strip()):
            return
        try:
            self.page.click(selector, timeout=3 * 1000)
        except TimeoutError as e:
            return

    def action_click_x_y(self, selector, value):
        x, y = value.strip().split(',')
        self.page.mouse.click(x=int(x.strip()), y=int(y.strip()))

    def action_wait_for_seconds(self, selector, value):
        self.page.wait_for_timeout(int(value) * 1000)

    # @todo - in the future make some popout interface to capture what needs to be set
    # https://playwright.dev/python/docs/api/class-keyboard
    def action_press_enter(self, selector, value):
        self.page.keyboard.press("Enter")

    def action_press_page_up(self, selector, value):
        self.page.keyboard.press("PageUp")

    def action_press_page_down(self, selector, value):
        self.page.keyboard.press("PageDown")

    def action_check_checkbox(self, selector, value):
        self.page.locator(selector).check()

    def action_uncheck_checkbox(self, selector, value):
        self.page.locator(selector).uncheck()


# Responsible for maintaining a live 'context' with browserless
# @todo - how long do contexts live for anyway?
class browsersteps_live_ui(steppable_browser_interface):

    context = None
    page = None
    render_extra_delay = 1
    # bump and kill this if idle after X sec
    age_start = 0

    # use a special driver, maybe locally etc
    command_executor = os.getenv(
        "PLAYWRIGHT_BROWSERSTEPS_DRIVER_URL"
    )
    # if not..
    if not command_executor:
        command_executor = os.getenv(
            "PLAYWRIGHT_DRIVER_URL",
            'ws://playwright-chrome:3000'
        ).strip('"')


    browser_type = os.getenv("PLAYWRIGHT_BROWSER_TYPE", 'chromium').strip('"')

    def __init__(self):
        self.age_start = time.time()
        #@ todo if content, and less than say 20 minutes in age_start to now remaining, create a new one
        if self.context is None:
            self.connect()


    # Connect and setup a new context
    def connect(self):
        # Should only get called once - test that

        logging.debug("browser_steps.py connecting")
        from playwright.sync_api import sync_playwright
        self.playwright = sync_playwright().start()
        keep_open = (60) * 60 * 1000

        self.browser = self.playwright.chromium.connect_over_cdp(self.command_executor+"&keepalive={}&timeout=600000".format(str(int(keep_open))))

        # @todo handle multiple contexts, bind a unique id from the browser on each req?
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

        self.page.set_default_navigation_timeout(keep_open)
        self.page.set_default_timeout(keep_open)



    def get_current_state(self):
        """Return the screenshot and interactive elements mapping, generally always called after action_()"""

        from . import content_fetcher
        self.page.wait_for_timeout(1 * 1000)
        # Quality set to 1 because it's not used, just used as a work-around for a bug, no need to change this.
        self.page.screenshot(type='jpeg', clip={'x': 1.0, 'y': 1.0, 'width': 1280, 'height': 1024}, quality=1)

        # The actual screenshot
        screenshot = self.page.screenshot(type='jpeg', full_page=True, quality=50)

        self.page.evaluate("var css_filter=''")
        elements = 'input, select, p,i, div,span,form,table,tbody,tr,td,a,p,ul,li,h1,h2,h3,h4, header, footer, section, article, aside, details, main, nav, section, summary'
        xpath_data = self.page.evaluate("async () => {" + content_fetcher.xpath_element_js.replace('%ELEMENTS%', elements) + "}")

        # except
        # playwright._impl._api_types.Error: Browser closed.
        return (screenshot, xpath_data)
