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
            #self.page.set_viewport_size({"width": 1280, "height": 5000})
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
        self.page.fill(selector, value, timeout=2 * 1000)

    def action_click_element(self, selector, value):
        if not len(selector.strip()):
            return
        self.page.click(selector, timeout=2 * 1000)

    def action_click_element_if_exists(self, selector, value):
        if not len(selector.strip()):
            return
        try:
            self.page.click(selector, timeout=2 * 1000)
        except TimeoutError as e:
            return

    def action_click_x_y(self, selector, value):
        x, y = value.strip().split(',')
        x = int(float(x.strip()))
        y = int(float(y.strip()))
        self.page.mouse.click(x=x, y=y)

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

    def __init__(self, playwright_browser):
        self.age_start = time.time()
        self.playwright_browser = playwright_browser
        #@ todo if content, and less than say 20 minutes in age_start to now remaining, create a new one
        if self.context is None:
            self.connect()


    # Connect and setup a new context
    def connect(self):
        # Should only get called once - test that
        keep_open = 1000 * 60 * 5

        # @todo handle multiple contexts, bind a unique id from the browser on each req?
        self.context = self.playwright_browser.new_context(
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
         # @todo probably this doesnt work
        self.page.on(
            "close",
            self.mark_as_closed,
        )
        self.page.wait_for_timeout(1 * 1000)

    # @todo I dont think this works
    def mark_as_closed(self):
        print("Page closed")
        self.page=None

    @property
    def has_expired(self):
        if not self.page:
            return True

        # 30 seconds enough? unsure
        #return time.time() - self.age_start > 30

    def get_current_state(self):
        """Return the screenshot and interactive elements mapping, generally always called after action_()"""

        from . import content_fetcher
        self.page.wait_for_timeout(1 * 1000)

        # The actual screenshot
        screenshot = self.page.screenshot(type='jpeg', full_page=True, quality=40)

        self.page.evaluate("var include_filters=''")
        elements = 'a, button, input, select, textarea, p,i, div,span,form,table,tbody,tr,td,a,p,ul,li,h1,h2,h3,h4, details, main, nav'
        xpath_data = self.page.evaluate("async () => {" + content_fetcher.xpath_element_js.replace('%ELEMENTS%', elements) + "}")
        # So the JS will find the smallest one first
        xpath_data['size_pos'] = sorted(xpath_data['size_pos'], key=lambda k: k['width']*k['height'], reverse=True)

        # except
        # playwright._impl._api_types.Error: Browser closed.
        # @todo show some countdown timer?
        return (screenshot, xpath_data)

    def request_visualselector_data(self):
        """
        Does the same that the playwright operation in content_fetcher does
        @todo refactor and remove duplicate code, add include_filters
        :param xpath_data:
        :param screenshot:
        :param current_include_filters:
        :return:
        """

        from . import content_fetcher
        self.page.evaluate("var include_filters=''")
        xpath_data = self.page.evaluate("async () => {" + content_fetcher.xpath_element_js.replace('%ELEMENTS%',
                                                                                        'div,span,form,table,tbody,tr,td,a,p,ul,li,h1,h2,h3,h4, header, footer, section, article, aside, details, main, nav, section, summary') + "}")

        screenshot = self.page.screenshot(type='jpeg', full_page=True, quality=int(os.getenv("PLAYWRIGHT_SCREENSHOT_QUALITY", 72)))

        return (screenshot, xpath_data)