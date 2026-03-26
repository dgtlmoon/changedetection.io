"""
Playwright CDP fetcher — connects to a remote browser via Chrome DevTools Protocol.

browser_connection_url must be supplied via the resolved BrowserProfile
(set by preconfigure_browser_profiles_based_on_env at startup or edited in the UI).
"""
from loguru import logger
from changedetectionio.pluggy_interface import hookimpl
from changedetectionio.content_fetchers.playwright import PlaywrightBaseFetcher


class fetcher(PlaywrightBaseFetcher):
    fetcher_description = "Playwright Chrome (CDP/Remote)"
    requires_connection_url = True
    ua_settings_key = 'playwright'  # matches DefaultUAInputForm field name

    def __init__(self, proxy_override=None, custom_browser_connection_url=None, **kwargs):
        super().__init__(proxy_override=proxy_override, custom_browser_connection_url=custom_browser_connection_url, **kwargs)

        if custom_browser_connection_url:
            self.browser_connection_is_custom = True
            self.browser_connection_url = custom_browser_connection_url
        else:
            logger.critical("Playwright CDP fetcher has no browser_connection_url — browser profile was not configured. "
                            "Set PLAYWRIGHT_DRIVER_URL or configure a browser profile in Settings.")
            self.browser_connection_url = None

        # CDP always connects to Chromium
        self.browser_type = 'chromium'

    async def _connect_browser(self, p):
        browser_type = getattr(p, self.browser_type)
        return await browser_type.connect_over_cdp(self.browser_connection_url, timeout=60_000)


class PlaywrightCDPPlugin:
    @hookimpl
    def register_content_fetcher(self):
        return ('playwright_cdp', fetcher)


cdp_plugin = PlaywrightCDPPlugin()
