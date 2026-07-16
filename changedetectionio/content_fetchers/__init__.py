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


def available_fetchers():
    # See the if statement at the bottom of this file for how we switch between playwright and webdriver
    import inspect
    p = []

    # Get built-in fetchers (but skip plugin fetchers that were added via setattr)
    for name, obj in inspect.getmembers(sys.modules[__name__], inspect.isclass):
        if inspect.isclass(obj):
            # @todo html_ is maybe better as fetcher_ or something
            # In this case, make sure to edit the default one in store.py and fetch_site_status.py
            if name.startswith('html_'):
                # Skip plugin fetchers that were already registered
                if name not in _plugin_fetchers:
                    t = tuple([name, obj.fetcher_description])
                    p.append(t)

    # Get plugin fetchers from cache (already loaded at module init)
    for name, fetcher_class in _plugin_fetchers.items():
        if hasattr(fetcher_class, 'fetcher_description'):
            t = tuple([name, fetcher_class.fetcher_description])
            p.append(t)
        else:
            logger.warning(f"Plugin fetcher '{name}' does not have fetcher_description attribute")

    return p


def get_plugin_fetchers():
    """Load and return all plugin fetchers from the centralized plugin manager."""
    from changedetectionio.pluggy_interface import plugin_manager

    fetchers = {}
    try:
        # Call the register_content_fetcher hook from all registered plugins
        results = plugin_manager.hook.register_content_fetcher()
        for result in results:
            if result:
                name, fetcher_class = result
                fetchers[name] = fetcher_class
                # Register in current module so hasattr() checks work
                setattr(sys.modules[__name__], name, fetcher_class)
                logger.info(f"Registered plugin fetcher: {name} - {getattr(fetcher_class, 'fetcher_description', 'No description')}")
    except Exception as e:
        logger.error(f"Error loading plugin fetchers: {e}")

    return fetchers


# Initialize plugins at module load time
_plugin_fetchers = get_plugin_fetchers()


def _log_fetcher_capabilities(fetcher_class, backend_name, uuid=None):
    """logger.info the capabilities of a resolved content fetcher class.

    Returns the FetcherCapabilities instance so callers can reuse it.
    """
    from changedetectionio.content_fetchers.base import FetcherCapabilities
    caps = FetcherCapabilities.from_fetcher(fetcher_class)
    logger.info(
        f"Content fetcher '{backend_name}' ({getattr(fetcher_class, 'fetcher_description', 'No description')})"
        f"{f' for watch {uuid}' if uuid else ''} - capabilities: "
        f"browser_steps={caps.supports_browser_steps}, "
        f"screenshots={caps.supports_screenshots}, "
        f"xpath_element_data={caps.supports_xpath_element_data}"
    )
    return caps


def resolve_content_fetcher(watch, datastore):
    """Single source of truth for resolving which content fetcher a watch should use.

    Resolution order (room to grow):
      1. Watch-level `fetch_backend`
      2. (future) group-level default
      3. System/global default from application settings

    Also collapses the special backend forms into a concrete fetcher:
      - 'system'                    -> global application default
      - 'extra_browser_<key>'       -> html_webdriver + custom connection URL
      - is_pdf watch                -> forced html_requests (browser PDF support incomplete)
      - html_webdriver + browser_steps -> playwright override (puppeteer steps incomplete)

    Returns:
        tuple: (fetcher_class, backend_name, custom_browser_connection_url, browser_config)
        where `backend_name` is the fully-resolved concrete backend name the caller should
        stamp onto the fetcher instance as `.backend_name`, and `browser_config` is the
        resolved FetcherConfig to inject as `.browser_config`.
    """
    this_module = sys.modules[__name__]
    from changedetectionio.model.browser_config import (
        FetcherConfig, resolve_browser_config_override, BrowserConfigDoesntExist,
    )

    # Default behaviour = empty config (built-in engines / system default).
    browser_config = FetcherConfig()

    # Selection order: a group override wins, else the watch's own selector value.
    # The value is either a built-in engine name ('html_requests', 'html_webdriver',
    # 'extra_browser_*'), the sentinel 'system', or the stable id of a user browser config.
    override = resolve_browser_config_override(watch, datastore)
    selected = override['config_id'] if override else watch.get('fetch_backend', 'system')

    # 'system' -> the global default, which may itself be a browser-config id or an engine name.
    if not selected or selected == 'system':
        selected = datastore.data['settings']['application'].get('fetch_backend')

    store = getattr(datastore, 'browser_config_store', None)
    entry = store.get(selected) if (store and selected) else None
    if entry:
        # A user-defined browser: its base_fetcher is the engine, plus its behaviour config.
        prefer_fetch_backend = entry.get('base_fetcher') or 'html_webdriver'
        browser_config = FetcherConfig(**(entry.get('browser_config') or {}))
    else:
        # Not a stored browser config. The only valid non-config values are a built-in engine
        # name or 'extra_browser_*'. Anything else is a reference to a browser config that has
        # been deleted - fail loudly instead of silently defaulting.
        if selected and selected != 'system' \
                and not selected.startswith('extra_browser_') \
                and not hasattr(this_module, selected):
            raise BrowserConfigDoesntExist(config_id=selected, uuid=watch.get('uuid'))
        prefer_fetch_backend = selected

    # Custom browser endpoint (extra_browser_<key>) -> webdriver with a specific connection URL
    custom_browser_connection_url = None
    if prefer_fetch_backend and prefer_fetch_backend.startswith('extra_browser_'):
        (t, key) = prefer_fetch_backend.split('extra_browser_')
        connection = list(
            filter(lambda s: (s['browser_name'] == key),
                   datastore.data['settings']['requests'].get('extra_browsers', [])))
        if connection:
            prefer_fetch_backend = 'html_webdriver'
            custom_browser_connection_url = connection[0].get('browser_connection_url')

    # PDF should be html_requests because playwright will serve it up (so far) in an embedded page
    # @todo https://github.com/dgtlmoon/changedetection.io/issues/2019
    if getattr(watch, 'is_pdf', False):
        logger.warning(
            f"Watch {watch.get('uuid')} is_pdf detected (content-type/url) - forcing the "
            f"'html_requests' fetcher because browser support isn't complete yet for "
            f"saving/downloading the PDF. Overriding requested backend '{prefer_fetch_backend}'."
        )
        prefer_fetch_backend = "html_requests"

    # Grab the right kind of 'fetcher' class (playwright, requests, plugin-provided, etc)
    if prefer_fetch_backend and hasattr(this_module, prefer_fetch_backend):
        # @todo TEMPORARY HACK - SWITCH BACK TO PLAYWRIGHT FOR BROWSERSTEPS
        if prefer_fetch_backend == 'html_webdriver' and getattr(watch, 'has_browser_steps', False):
            # This is never supported in selenium anyway
            logger.warning(
                "Using playwright fetcher override for possible puppeteer request in browsersteps, "
                "because puppetteer:browser steps is incomplete.")
            from changedetectionio.content_fetchers.playwright import fetcher as playwright_fetcher
            fetcher_obj = playwright_fetcher
        else:
            fetcher_obj = getattr(this_module, prefer_fetch_backend)
    else:
        # What it referenced doesn't exist, just use a default
        fetcher_obj = getattr(this_module, "html_requests")

    _log_fetcher_capabilities(fetcher_obj, prefer_fetch_backend, uuid=watch.get('uuid'))

    return fetcher_obj, prefer_fetch_backend, custom_browser_connection_url, browser_config


# Decide which is the 'real' HTML webdriver, this is more a system wide config
# rather than site-specific.
use_playwright_as_chrome_fetcher = os.getenv('PLAYWRIGHT_DRIVER_URL', False)
if use_playwright_as_chrome_fetcher:
    # @note - For now, browser steps always uses playwright
    if not strtobool(os.getenv('FAST_PUPPETEER_CHROME_FETCHER', 'False')):
        logger.debug('Using Playwright library as fetcher')
        from .playwright import fetcher as html_webdriver
    else:
        logger.debug('Using direct Python Puppeteer library as fetcher')
        from .puppeteer import fetcher as html_webdriver

else:
    logger.debug("Falling back to selenium as fetcher")
    from .webdriver_selenium import fetcher as html_webdriver


# Register built-in fetchers as plugins after all imports are complete
from changedetectionio.pluggy_interface import register_builtin_fetchers
register_builtin_fetchers()

