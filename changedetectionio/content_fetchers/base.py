import os
from abc import abstractmethod
from loguru import logger

from changedetectionio.content_fetchers import BrowserStepsStepException


def manage_user_agent(headers, current_ua=''):
    """
    Basic setting of user-agent

    NOTE!!!!!! The service that does the actual Chrome fetching should handle any anti-robot techniques
    THERE ARE MANY WAYS THAT IT CAN BE DETECTED AS A ROBOT!!
    This does not take care of
    - Scraping of 'navigator' (platform, productSub, vendor, oscpu etc etc) browser object (navigator.appVersion) etc
    - TCP/IP fingerprint JA3 etc
    - Graphic rendering fingerprinting
    - Your IP being obviously in a pool of bad actors
    - Too many requests
    - Scraping of SCH-UA browser replies (thanks google!!)
    - Scraping of ServiceWorker, new window calls etc

    See https://filipvitas.medium.com/how-to-set-user-agent-header-with-puppeteer-js-and-not-fail-28c7a02165da
    Puppeteer requests https://github.com/dgtlmoon/pyppeteerstealth

    :param page:
    :param headers:
    :return:
    """
    # Ask it what the user agent is, if its obviously ChromeHeadless, switch it to the default
    ua_in_custom_headers = headers.get('User-Agent')
    if ua_in_custom_headers:
        return ua_in_custom_headers

    if not ua_in_custom_headers and current_ua:
        current_ua = current_ua.replace('HeadlessChrome', 'Chrome')
        return current_ua

    return None


class Fetcher():
    browser_connection_is_custom = None
    browser_connection_url = None
    browser_steps = None
    browser_steps_screenshot_path = None
    content = None
    error = None
    fetcher_description = "No description"
    headers = {}
    instock_data = None
    instock_data_js = ""
    status_code = None
    webdriver_js_execute_code = None
    xpath_data = None
    xpath_element_js = ""

    # Will be needed in the future by the VisualSelector, always get this where possible.
    screenshot = False
    system_http_proxy = os.getenv('HTTP_PROXY')
    system_https_proxy = os.getenv('HTTPS_PROXY')

    # Time ONTOP of the system defined env minimum time
    render_extract_delay = 0

    def __init__(self):
        import importlib.resources
        self.xpath_element_js = importlib.resources.files("changedetectionio.content_fetchers.res").joinpath('xpath_element_scraper.js').read_text(encoding='utf-8')
        self.instock_data_js = importlib.resources.files("changedetectionio.content_fetchers.res").joinpath('stock-not-in-stock.js').read_text(encoding='utf-8')

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
            is_binary=False,
            empty_pages_are_a_change=False):
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
        if self.browser_steps_screenshot_path and not os.path.isdir(self.browser_steps_screenshot_path):
            logger.debug(f"> Creating data dir {self.browser_steps_screenshot_path}")
            os.mkdir(self.browser_steps_screenshot_path)
        return None

    @abstractmethod
    # Return true/false if this checker is ready to run, in the case it needs todo some special config check etc
    def is_ready(self):
        return True

    def get_all_headers(self):
        """
        Get all headers but ensure all keys are lowercase
        :return:
        """
        return {k.lower(): v for k, v in self.headers.items()}

    def browser_steps_get_valid_steps(self):
        if self.browser_steps is not None and len(self.browser_steps):
            valid_steps = list(filter(
                lambda s: (s['operation'] and len(s['operation']) and s['operation'] != 'Choose one'),
                self.browser_steps))

            # Just incase they selected Goto site by accident with older JS
            if valid_steps and valid_steps[0]['operation'] == 'Goto site':
                del(valid_steps[0])

            return valid_steps

        return None

    def iterate_browser_steps(self, start_url=None):
        from changedetectionio.blueprint.browser_steps.browser_steps import steppable_browser_interface
        from playwright._impl._errors import TimeoutError, Error
        from changedetectionio.safe_jinja import render as jinja_render
        step_n = 0

        if self.browser_steps is not None and len(self.browser_steps):
            interface = steppable_browser_interface(start_url=start_url)
            interface.page = self.page
            valid_steps = self.browser_steps_get_valid_steps()

            for step in valid_steps:
                step_n += 1
                logger.debug(f">> Iterating check - browser Step n {step_n} - {step['operation']}...")
                self.screenshot_step("before-" + str(step_n))
                self.save_step_html("before-" + str(step_n))
                try:
                    optional_value = step['optional_value']
                    selector = step['selector']
                    # Support for jinja2 template in step values, with date module added
                    if '{%' in step['optional_value'] or '{{' in step['optional_value']:
                        optional_value = jinja_render(template_str=step['optional_value'])
                    if '{%' in step['selector'] or '{{' in step['selector']:
                        selector = jinja_render(template_str=step['selector'])

                    getattr(interface, "call_action")(action_name=step['operation'],
                                                      selector=selector,
                                                      optional_value=optional_value)
                    self.screenshot_step(step_n)
                    self.save_step_html(step_n)
                except (Error, TimeoutError) as e:
                    logger.debug(str(e))
                    # Stop processing here
                    raise BrowserStepsStepException(step_n=step_n, original_e=e)

    # It's always good to reset these
    def delete_browser_steps_screenshots(self):
        import glob
        if self.browser_steps_screenshot_path is not None:
            dest = os.path.join(self.browser_steps_screenshot_path, 'step_*.jpeg')
            files = glob.glob(dest)
            for f in files:
                if os.path.isfile(f):
                    os.unlink(f)

    def save_step_html(self, step_n):
        if self.browser_steps_screenshot_path and not os.path.isdir(self.browser_steps_screenshot_path):
            logger.debug(f"> Creating data dir {self.browser_steps_screenshot_path}")
            os.mkdir(self.browser_steps_screenshot_path)
        pass
