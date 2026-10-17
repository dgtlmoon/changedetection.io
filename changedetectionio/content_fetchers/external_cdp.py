"""
html_external_cdp - an EXTERNAL Chrome you do not run: a CDP-over-WebSocket endpoint supplied
per browser config (Bright Data / Oxylabs Scraping Browser, browserless, a second
sockpuppetbrowser, ...).

Subclasses the tuned playwright.fetcher and overrides only where the connection URL comes from -
the browser config's `connection_url` instead of the PLAYWRIGHT_DRIVER_URL env var - so the whole
run() body (browser steps, screenshots, xpath, stitching) is shared.

Base-only (ready_to_use=False): the bare engine has nothing to connect to, so you create one
browser config ("variation") per endpoint. That list of endpoints is exactly what
settings.requests.extra_browsers used to be, and update_36 migrates them here.

Why this exists as its own engine rather than a string prefix: an 'extra_browser_<name>' URL was
handed to whatever html_webdriver resolved to at import time, so the SAME wss:// endpoint was
spoken to over CDP on a Playwright install, over CDP-with-pyppeteer on a FAST_PUPPETEER install,
and over the W3C WebDriver HTTP protocol on a Selenium-only install - where it cannot work at all.
Pinning the protocol to the engine, instead of inheriting it from an env var, is the point.
"""
from loguru import logger

from changedetectionio.content_fetchers.exceptions import BrowserConnectError
from changedetectionio.content_fetchers.playwright import fetcher as playwright_fetcher


class fetcher(playwright_fetcher):
    fetcher_description = "External CDP Browser"

    # Base-only: an endpoint is required, and it lives on the browser config - so this is offered
    # as a base to create variations from, never as a directly-selectable browser or the default.
    ready_to_use = False

    # The endpoint is per-config, which is what makes this engine worth having.
    supports_connection_url = True

    # Someone else's browser service handles its own egress (Bright Data et al route internally),
    # so our per-watch proxy must not be layered on top - it would be ignored at best, and at
    # worst send credentials to the wrong hop. Replaces the old 'extra_browser_' prefix check.
    ignores_proxy_setting = True

    @classmethod
    def browser_steps_connection_url(cls, browser_config=None):
        """Where this browser lives - for a fetch and for a live session alike.

        A variation always has an endpoint (the form requires it); a bare html_external_cdp
        selector - a watch edited by hand or via the API - does not.
        """
        url = (getattr(browser_config, 'connection_url', None) or '').strip()
        if not url:
            raise BrowserConnectError(msg="No browser endpoint configured for this External CDP "
                                          "Browser - set its connection URL on the Browsers page.")
        return url

    async def _get_browser(self, browser_type):
        # browser_config is injected after construction (call_browser), so this is read at fetch
        # time. Never logged: these endpoints commonly carry credentials in userinfo or query
        # args (Bright Data / Oxylabs zone tokens).
        url = self.browser_steps_connection_url(getattr(self, 'browser_config', None))
        logger.debug(f"html_external_cdp: connecting to external browser for watch "
                     f"{getattr(self, 'watch_uuid', None)}")
        self.browser_connection_url = url
        return await browser_type.connect_over_cdp(url, timeout=60000)


class ExternalCdpFetcherPlugin:
    def register_content_fetcher(self):
        return ('html_external_cdp', fetcher)


external_cdp_plugin = ExternalCdpFetcherPlugin()
