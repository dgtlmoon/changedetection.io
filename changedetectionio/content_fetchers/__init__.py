import sys
from changedetectionio.strtobool import strtobool
from loguru import logger
from changedetectionio.content_fetchers.exceptions import BrowserStepsStepException
import os

# Visual Selector scraper - 'Button' is there because some sites have <button>OUT OF STOCK</button>.
visualselector_xpath_selectors = 'div,span,form,table,tbody,tr,td,a,p,ul,li,h1,h2,h3,h4,header,footer,section,article,aside,details,main,nav,section,summary,button'

# Import hookimpl from centralized pluggy interface
from changedetectionio.pluggy_interface import hookimpl

SCREENSHOT_MAX_HEIGHT_DEFAULT = 20000
SCREENSHOT_DEFAULT_QUALITY = 40

# Maximum total height for the final image (When in stitch mode).
# We limit this to 16000px due to the huge amount of RAM that was being used
# Example: 16000 × 1400 × 3 = 67,200,000 bytes ≈ 64.1 MB (not including buffers in PIL etc)
SCREENSHOT_MAX_TOTAL_HEIGHT = int(os.getenv("SCREENSHOT_MAX_HEIGHT", SCREENSHOT_MAX_HEIGHT_DEFAULT))

# The size at which we will switch to stitching method, when below this (and
# MAX_TOTAL_HEIGHT which can be set by a user) we will use the default
# screenshot method.
# Increased from 8000 to 10000 for better performance (fewer chunks = faster)
# Most modern GPUs support 16384x16384 textures, so 1280x10000 is safe
SCREENSHOT_SIZE_STITCH_THRESHOLD = int(os.getenv("SCREENSHOT_CHUNK_HEIGHT", 10000))

# available_fetchers() will scan this implementation looking for anything starting with html_
# this information is used in the form selections
from changedetectionio.content_fetchers.requests import fetcher as html_requests


import importlib.resources
XPATH_ELEMENT_JS = importlib.resources.files("changedetectionio.content_fetchers.res").joinpath('xpath_element_scraper.js').read_text(encoding='utf-8')
INSTOCK_DATA_JS = importlib.resources.files("changedetectionio.content_fetchers.res").joinpath('stock-not-in-stock.js').read_text(encoding='utf-8')
FAVICON_FETCHER_JS = importlib.resources.files("changedetectionio.content_fetchers.res").joinpath('favicon-fetcher.js').read_text(encoding='utf-8')


# Registry: clean fetcher name → fetcher class (e.g. 'requests', 'playwright', 'cloakbrowser')
FETCHERS: dict = {}


def register_fetcher(name: str, cls) -> None:
    """Register a fetcher class under its clean name (no html_ prefix)."""
    FETCHERS[name] = cls


def get_fetcher(name: str):
    """Return the fetcher class for a clean name, or None."""
    return FETCHERS.get(name)


def available_fetchers():
    """Return list of (name, description) for all registered fetchers."""
    return [(name, cls.fetcher_description) for name, cls in FETCHERS.items()
            if hasattr(cls, 'fetcher_description')]


def _load_fetchers():
    """Load all fetchers (built-ins + plugins) into the FETCHERS registry."""
    from changedetectionio.pluggy_interface import plugin_manager, register_builtin_fetchers

    # Built-ins must be registered first
    register_builtin_fetchers()

    # Then external plugins
    try:
        results = plugin_manager.hook.register_content_fetcher()
        for result in results:
            if result:
                name, fetcher_class = result
                register_fetcher(name, fetcher_class)
                logger.info(f"Registered fetcher: {name} - {getattr(fetcher_class, 'fetcher_description', '?')}")
    except Exception as e:
        logger.error(f"Error loading plugin fetchers: {e}")


def get_active_browser_fetcher_name() -> str:
    """Return the clean name of the browser fetcher activated by environment config.

    - ``PLAYWRIGHT_DRIVER_URL`` set + ``FAST_PUPPETEER_CHROME_FETCHER=False`` → ``playwright``
    - ``PLAYWRIGHT_DRIVER_URL`` set + ``FAST_PUPPETEER_CHROME_FETCHER=True``  → ``puppeteer``
    - Neither set → ``selenium``
    """
    if os.getenv('PLAYWRIGHT_DRIVER_URL', False):
        if not strtobool(os.getenv('FAST_PUPPETEER_CHROME_FETCHER', 'False')):
            return 'playwright'
        return 'puppeteer'
    return 'selenium'


# Populate the registry at module load time
_load_fetchers()

# Convenience module-level aliases (clean names, no html_ prefix)
html_requests  = FETCHERS.get('requests')   # backwards-compat alias
html_playwright = FETCHERS.get('playwright') # backwards-compat alias
html_selenium  = FETCHERS.get('selenium')   # backwards-compat alias
html_puppeteer = FETCHERS.get('puppeteer')  # backwards-compat alias

