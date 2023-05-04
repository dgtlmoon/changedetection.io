from abc import abstractmethod
import os
from . import exceptions

visualselector_xpath_selectors = 'div,span,form,table,tbody,tr,td,a,p,ul,li,h1,h2,h3,h4, header, footer, section, article, aside, details, main, nav, section, summary'


class Fetcher():
    browser_steps = None
    browser_steps_screenshot_path = None
    content = None
    error = None
    fetcher_description = "No description"
    headers = None
    status_code = None
    webdriver_js_execute_code = None
    xpath_data = None
    xpath_element_js = ""
    instock_data = None
    instock_data_js = ""

    # Will be needed in the future by the VisualSelector, always get this where possible.
    screenshot = False
    system_http_proxy = os.getenv('HTTP_PROXY')
    system_https_proxy = os.getenv('HTTPS_PROXY')

    # Time ONTOP of the system defined env minimum time
    render_extract_delay = 0

    def __init__(self):
        from pkg_resources import resource_string
        # The code that scrapes elements and makes a list of elements/size/position to click on in the VisualSelector
        self.xpath_element_js = resource_string(__name__, "../res/xpath_element_scraper.js").decode('utf-8')
        self.instock_data_js = resource_string(__name__, "../res/stock-not-in-stock.js").decode('utf-8')


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
            is_binary=False):
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
        return None

    @abstractmethod
    # Return true/false if this checker is ready to run, in the case it needs todo some special config check etc
    def is_ready(self):
        return True

    def iterate_browser_steps(self):
        from changedetectionio.blueprint.browser_steps.browser_steps import steppable_browser_interface
        from playwright._impl._api_types import TimeoutError
        from jinja2 import Environment
        jinja2_env = Environment(extensions=['jinja2_time.TimeExtension'])

        step_n = 0

        if self.browser_steps is not None and len(self.browser_steps):
            interface = steppable_browser_interface()
            interface.page = self.page

            valid_steps = filter(lambda s: (s['operation'] and len(s['operation']) and s['operation'] != 'Choose one' and s['operation'] != 'Goto site'), self.browser_steps)

            for step in valid_steps:
                step_n += 1
                print(">> Iterating check - browser Step n {} - {}...".format(step_n, step['operation']))
                self.screenshot_step("before-"+str(step_n))
                self.save_step_html("before-"+str(step_n))
                try:
                    optional_value = step['optional_value']
                    selector = step['selector']
                    # Support for jinja2 template in step values, with date module added
                    if '{%' in step['optional_value'] or '{{' in step['optional_value']:
                        optional_value = str(jinja2_env.from_string(step['optional_value']).render())
                    if '{%' in step['selector'] or '{{' in step['selector']:
                        selector = str(jinja2_env.from_string(step['selector']).render())

                    getattr(interface, "call_action")(action_name=step['operation'],
                                                      selector=selector,
                                                      optional_value=optional_value)
                    self.screenshot_step(step_n)
                    self.save_step_html(step_n)
                except TimeoutError:
                    # Stop processing here
                    raise exceptions.BrowserStepsStepTimout(step_n=step_n)



    # It's always good to reset these
    def delete_browser_steps_screenshots(self):
        import glob
        if self.browser_steps_screenshot_path is not None:
            dest = os.path.join(self.browser_steps_screenshot_path, 'step_*.jpeg')
            files = glob.glob(dest)
            for f in files:
                os.unlink(f)

#   Maybe for the future, each fetcher provides its own diff output, could be used for text, image
#   the current one would return javascript output (as we use JS to generate the diff)
#


def available_fetchers():
    from . import playwright, html_requests, webdriver

    p = []
    p.append(tuple(['html_requests', html_requests.fetcher.fetcher_description]))

    # Prefer playwright
    if os.getenv('PLAYWRIGHT_DRIVER_URL', False):
        p.append(tuple(['html_webdriver', playwright.fetcher.fetcher_description]))

    elif os.getenv('WEBDRIVER_URL'):
        p.append(tuple(['html_webdriver', webdriver.fetcher.fetcher_description]))


    return p

html_webdriver = None
# Decide which is the 'real' HTML webdriver, this is more a system wide config rather than site-specific.
use_playwright_as_chrome_fetcher = os.getenv('PLAYWRIGHT_DRIVER_URL', False)
if use_playwright_as_chrome_fetcher:
    from . import playwright
    html_webdriver = getattr(playwright, "fetcher")

else:
    from . import webdriver
    html_webdriver = getattr(webdriver, "fetcher")

