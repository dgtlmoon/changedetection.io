import os
import time
import re
from random import randint
from loguru import logger

from changedetectionio.content_fetchers import SCREENSHOT_MAX_HEIGHT_DEFAULT
from changedetectionio.content_fetchers.base import manage_user_agent
from changedetectionio.safe_jinja import render as jinja_render



# Two flags, tell the JS which of the "Selector" or "Value" field should be enabled in the front end
# 0- off, 1- on
browser_step_ui_config = {'Choose one': '0 0',
                          #                 'Check checkbox': '1 0',
                          #                 'Click button containing text': '0 1',
                          #                 'Scroll to bottom': '0 0',
                          #                 'Scroll to element': '1 0',
                          #                 'Scroll to top': '0 0',
                          #                 'Switch to iFrame by index number': '0 1'
                          #                 'Uncheck checkbox': '1 0',
                          # @todo
                          'Check checkbox': '1 0',
                          'Click X,Y': '0 1',
                          'Click element if exists': '1 0',
                          'Click element': '1 0',
                          'Click element containing text': '0 1',
                          'Click element containing text if exists': '0 1',
                          'Enter text in field': '1 1',
                          'Execute JS': '0 1',
#                          'Extract text and use as filter': '1 0',
                          'Goto site': '0 0',
                          'Goto URL': '0 1',
                          'Make all child elements visible': '1 0',
                          'Press Enter': '0 0',
                          'Select by label': '1 1',
                          '<select> by option text': '1 1',
                          'Scroll down': '0 0',
                          'Uncheck checkbox': '1 0',
                          'Wait for seconds': '0 1',
                          'Wait for text': '0 1',
                          'Wait for text in element': '1 1',
                          'Remove elements': '1 0',
                          #                          'Press Page Down': '0 0',
                          #                          'Press Page Up': '0 0',
                          # weird bug, come back to it later
                          }


# Good reference - https://playwright.dev/python/docs/input
#                  https://pythonmana.com/2021/12/202112162236307035.html
#
# ONLY Works in Playwright because we need the fullscreen screenshot
class steppable_browser_interface():
    page = None
    start_url = None
    action_timeout = 10 * 1000

    def __init__(self, start_url):
        self.start_url = start_url

    # Convert and perform "Click Button" for example
    async def call_action(self, action_name, selector=None, optional_value=None):
        if self.page is None:
            logger.warning("Cannot call action on None page object")
            return
            
        now = time.time()
        call_action_name = re.sub('[^0-9a-zA-Z]+', '_', action_name.lower())
        if call_action_name == 'choose_one':
            return

        logger.debug(f"> Action calling '{call_action_name}'")
        # https://playwright.dev/python/docs/selectors#xpath-selectors
        if selector and selector.startswith('/') and not selector.startswith('//'):
            selector = "xpath=" + selector

        # Check if action handler exists
        if not hasattr(self, "action_" + call_action_name):
            logger.warning(f"Action handler for '{call_action_name}' not found")
            return
            
        action_handler = getattr(self, "action_" + call_action_name)

        # Support for Jinja2 variables in the value and selector
        if selector and ('{%' in selector or '{{' in selector):
            selector = jinja_render(template_str=selector)

        if optional_value and ('{%' in optional_value or '{{' in optional_value):
            optional_value = jinja_render(template_str=optional_value)

        # Trigger click and cautiously handle potential navigation
        # This means the page redirects/reloads/changes JS etc etc
        if call_action_name.startswith('click_'):
            try:
                # Set up navigation expectation before the click (like sync version)
                async with self.page.expect_event("framenavigated", timeout=3000) as navigation_info:
                    await action_handler(selector, optional_value)
                
                # Check if navigation actually occurred
                try:
                    await navigation_info.value  # This waits for the navigation promise
                    logger.debug(f"Navigation occurred on {call_action_name}.")
                except Exception:
                    logger.debug(f"No navigation occurred within timeout when calling {call_action_name}, that's OK, continuing.")
                    
            except Exception as e:
                # If expect_event itself times out, that means no navigation occurred - that's OK
                if "framenavigated" in str(e) and "exceeded" in str(e):
                    logger.debug(f"No navigation occurred within timeout when calling {call_action_name}, that's OK, continuing.")
                else:
                    raise e
        else:
            # Some other action that probably a navigation is not expected
            await action_handler(selector, optional_value)


        # Safely wait for timeout
        await self.page.wait_for_timeout(1.5 * 1000)
        logger.debug(f"Call action done in {time.time()-now:.2f}s")

    async def action_goto_url(self, selector=None, value=None):
        if not value:
            logger.warning("No URL provided for goto_url action")
            return None
            
        now = time.time()
        response = await self.page.goto(value, timeout=0, wait_until='load')
        logger.debug(f"Time to goto URL {time.time()-now:.2f}s")
        return response

    # Incase they request to go back to the start
    async def action_goto_site(self, selector=None, value=None):
        return await self.action_goto_url(value=re.sub(r'^source:', '', self.start_url, flags=re.IGNORECASE))

    async def action_click_element_containing_text(self, selector=None, value=''):
        logger.debug("Clicking element containing text")
        if not value or not len(value.strip()):
            return
            
        elem = self.page.get_by_text(value)
        if await elem.count():
            await elem.first.click(delay=randint(200, 500), timeout=self.action_timeout)


    async def action_click_element_containing_text_if_exists(self, selector=None, value=''):
        logger.debug("Clicking element containing text if exists")
        if not value or not len(value.strip()):
            return
            
        elem = self.page.get_by_text(value)
        count = await elem.count()
        logger.debug(f"Clicking element containing text - {count} elements found")
        if count:
            await elem.first.click(delay=randint(200, 500), timeout=self.action_timeout)
                

    async def action_enter_text_in_field(self, selector, value):
        if not selector or not len(selector.strip()):
            return

        await self.page.fill(selector, value, timeout=self.action_timeout)

    async def action_execute_js(self, selector, value):
        if not value:
            return None
            
        return await self.page.evaluate(value)

    async def action_click_element(self, selector, value):
        logger.debug("Clicking element")
        if not selector or not len(selector.strip()):
            return

        await self.page.click(selector=selector, timeout=self.action_timeout + 20 * 1000, delay=randint(200, 500))

    async def action_click_element_if_exists(self, selector, value):
        import playwright._impl._errors as _api_types
        logger.debug("Clicking element if exists")
        if not selector or not len(selector.strip()):
            return
            
        try:
            await self.page.click(selector, timeout=self.action_timeout, delay=randint(200, 500))
        except _api_types.TimeoutError:
            return
        except _api_types.Error:
            # Element was there, but page redrew and now its long long gone
            return
                

    async def action_click_x_y(self, selector, value):
        if not value or not re.match(r'^\s?\d+\s?,\s?\d+\s?$', value):
            logger.warning("'Click X,Y' step should be in the format of '100 , 90'")
            return

        try:
            x, y = value.strip().split(',')
            x = int(float(x.strip()))
            y = int(float(y.strip()))
            
            await self.page.mouse.click(x=x, y=y, delay=randint(200, 500))
                
        except Exception as e:
            logger.error(f"Error parsing x,y coordinates: {str(e)}")

    async def action__select_by_option_text(self, selector, value):
        if not selector or not len(selector.strip()):
            return

        await self.page.select_option(selector, label=value, timeout=self.action_timeout)

    async def action_scroll_down(self, selector, value):
        # Some sites this doesnt work on for some reason
        await self.page.mouse.wheel(0, 600)
        await self.page.wait_for_timeout(1000)

    async def action_wait_for_seconds(self, selector, value):
        try:
            seconds = float(value.strip()) if value else 1.0
            await self.page.wait_for_timeout(seconds * 1000)
        except (ValueError, TypeError) as e:
            logger.error(f"Invalid value for wait_for_seconds: {str(e)}")

    async def action_wait_for_text(self, selector, value):
        if not value:
            return
            
        import json
        v = json.dumps(value)
        await self.page.wait_for_function(
            f'document.querySelector("body").innerText.includes({v});',
            timeout=30000
        )
            

    async def action_wait_for_text_in_element(self, selector, value):
        if not selector or not value:
            return
            
        import json
        s = json.dumps(selector)
        v = json.dumps(value)
        
        await self.page.wait_for_function(
            f'document.querySelector({s}).innerText.includes({v});',
            timeout=30000
        )

    # @todo - in the future make some popout interface to capture what needs to be set
    # https://playwright.dev/python/docs/api/class-keyboard
    async def action_press_enter(self, selector, value):
        await self.page.keyboard.press("Enter", delay=randint(200, 500))
            

    async def action_press_page_up(self, selector, value):
        await self.page.keyboard.press("PageUp", delay=randint(200, 500))

    async def action_press_page_down(self, selector, value):
        await self.page.keyboard.press("PageDown", delay=randint(200, 500))

    async def action_check_checkbox(self, selector, value):
        if not selector:
            return

        await self.page.locator(selector).check(timeout=self.action_timeout)

    async def action_uncheck_checkbox(self, selector, value):
        if not selector:
            return
            
        await self.page.locator(selector).uncheck(timeout=self.action_timeout)
            

    async def action_remove_elements(self, selector, value):
        """Removes all elements matching the given selector from the DOM."""
        if not selector:
            return
            
        await self.page.locator(selector).evaluate_all("els => els.forEach(el => el.remove())")

    async def action_make_all_child_elements_visible(self, selector, value):
        """Recursively makes all child elements inside the given selector fully visible."""
        if not selector:
            return
            
        await self.page.locator(selector).locator("*").evaluate_all("""
            els => els.forEach(el => {
                el.style.display = 'block';   // Forces it to be displayed
                el.style.visibility = 'visible';   // Ensures it's not hidden
                el.style.opacity = '1';   // Fully opaque
                el.style.position = 'relative';   // Avoids 'absolute' hiding
                el.style.height = 'auto';   // Expands collapsed elements
                el.style.width = 'auto';   // Ensures full visibility
                el.removeAttribute('hidden');   // Removes hidden attribute
                el.classList.remove('hidden', 'd-none');  // Removes common CSS hidden classes
            })
        """)

# Responsible for maintaining a live 'context' with the chrome CDP
# @todo - how long do contexts live for anyway?
class browsersteps_live_ui(steppable_browser_interface):
    context = None
    page = None
    render_extra_delay = 1
    stale = False
    # bump and kill this if idle after X sec
    age_start = 0
    headers = {}
    # Track if resources are properly cleaned up
    _is_cleaned_up = False
    
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

    def __init__(self, playwright_browser, proxy=None, headers=None, start_url=None):
        self.headers = headers or {}
        self.age_start = time.time()
        self.playwright_browser = playwright_browser
        self.start_url = start_url
        self._is_cleaned_up = False
        self.proxy = proxy
        # Note: connect() is now async and must be called separately

    def __del__(self):
        # Ensure cleanup happens if object is garbage collected
        # Note: cleanup is now async, so we can only mark as cleaned up here
        self._is_cleaned_up = True

    # Connect and setup a new context
    async def connect(self, proxy=None):
        # Should only get called once - test that
        keep_open = 1000 * 60 * 5
        now = time.time()

        # @todo handle multiple contexts, bind a unique id from the browser on each req?
        self.context = await self.playwright_browser.new_context(
            accept_downloads=False,  # Should never be needed
            bypass_csp=True,  # This is needed to enable JavaScript execution on GitHub and others
            extra_http_headers=self.headers,
            ignore_https_errors=True,
            proxy=proxy,
            service_workers=os.getenv('PLAYWRIGHT_SERVICE_WORKERS', 'allow'),
            # Should be `allow` or `block` - sites like YouTube can transmit large amounts of data via Service Workers
            user_agent=manage_user_agent(headers=self.headers),
        )

        self.page = await self.context.new_page()

        # self.page.set_default_navigation_timeout(keep_open)
        self.page.set_default_timeout(keep_open)
        # Set event handlers
        self.page.on("close", self.mark_as_closed)
        # Listen for all console events and handle errors
        self.page.on("console", lambda msg: print(f"Browser steps console - {msg.type}: {msg.text} {msg.args}"))

        logger.debug(f"Time to browser setup {time.time()-now:.2f}s")
        await self.page.wait_for_timeout(1 * 1000)

    def mark_as_closed(self):
        logger.debug("Page closed, cleaning up..")
        # Note: This is called from a sync context (event handler)
        # so we'll just mark as cleaned up and let __del__ handle the rest
        self._is_cleaned_up = True

    async def cleanup(self):
        """Properly clean up all resources to prevent memory leaks"""
        if self._is_cleaned_up:
            return
            
        logger.debug("Cleaning up browser steps resources")
        
        # Clean up page
        if hasattr(self, 'page') and self.page is not None:
            try:
                # Force garbage collection before closing
                await self.page.request_gc()
            except Exception as e:
                logger.debug(f"Error during page garbage collection: {str(e)}")
                
            try:
                # Remove event listeners before closing
                self.page.remove_listener("close", self.mark_as_closed)
            except Exception as e:
                logger.debug(f"Error removing event listeners: {str(e)}")
                
            try:
                await self.page.close()
            except Exception as e:
                logger.debug(f"Error closing page: {str(e)}")
            
            self.page = None

        # Clean up context
        if hasattr(self, 'context') and self.context is not None:
            try:
                await self.context.close()
            except Exception as e:
                logger.debug(f"Error closing context: {str(e)}")
            
            self.context = None
            
        self._is_cleaned_up = True
        logger.debug("Browser steps resources cleanup complete")

    @property
    def has_expired(self):
        if not self.page or self._is_cleaned_up:
            return True
        
        # Check if session has expired based on age
        max_age_seconds = int(os.getenv("BROWSER_STEPS_MAX_AGE_SECONDS", 60 * 10))  # Default 10 minutes
        if (time.time() - self.age_start) > max_age_seconds:
            logger.debug(f"Browser steps session expired after {max_age_seconds} seconds")
            return True
            
        return False

    async def get_current_state(self):
        """Return the screenshot and interactive elements mapping, generally always called after action_()"""
        import importlib.resources
        import json
        # because we for now only run browser steps in playwright mode (not puppeteer mode)
        from changedetectionio.content_fetchers.playwright import capture_full_page_async

        # Safety check - don't proceed if resources are cleaned up
        if self._is_cleaned_up or self.page is None:
            logger.warning("Attempted to get current state after cleanup")
            return (None, None)

        xpath_element_js = importlib.resources.files("changedetectionio.content_fetchers.res").joinpath('xpath_element_scraper.js').read_text()

        now = time.time()
        await self.page.wait_for_timeout(1 * 1000)

        screenshot = None
        xpath_data = None
        
        try:
            # Get screenshot first
            screenshot = await capture_full_page_async(page=self.page)
            if not screenshot:
                logger.error("No screenshot was retrieved :((")

            logger.debug(f"Time to get screenshot from browser {time.time() - now:.2f}s")

            # Then get interactive elements
            now = time.time()
            await self.page.evaluate("var include_filters=''")
            await self.page.request_gc()

            scan_elements = 'a,button,input,select,textarea,i,th,td,p,li,h1,h2,h3,h4,div,span'

            MAX_TOTAL_HEIGHT = int(os.getenv("SCREENSHOT_MAX_HEIGHT", SCREENSHOT_MAX_HEIGHT_DEFAULT))
            xpath_data = json.loads(await self.page.evaluate(xpath_element_js, {
                "visualselector_xpath_selectors": scan_elements,
                "max_height": MAX_TOTAL_HEIGHT
            }))
            await self.page.request_gc()

            # Sort elements by size
            xpath_data['size_pos'] = sorted(xpath_data['size_pos'], key=lambda k: k['width'] * k['height'], reverse=True)
            logger.debug(f"Time to scrape xPath element data in browser {time.time()-now:.2f}s")
            
        except Exception as e:
            logger.error(f"Error getting current state: {str(e)}")
            # If the page has navigated (common with logins) then the context is destroyed on navigation, continue
            # I'm not sure that this is required anymore because we have the "expect navigation wrapper" at the top
            if "Execution context was destroyed" in str(e):
                logger.debug("Execution context was destroyed, most likely because of navigation, continuing...")
            pass

            # Attempt recovery - force garbage collection
            try:
                await self.page.request_gc()
            except:
                pass
        
        # Request garbage collection one final time
        try:
            await self.page.request_gc()
        except:
            pass
            
        return (screenshot, xpath_data)

