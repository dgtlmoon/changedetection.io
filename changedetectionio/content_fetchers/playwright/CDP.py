"""
Playwright CDP fetcher — connects to a remote browser via Chrome DevTools Protocol.

This is the original "playwright" fetcher, renamed to make the connection
method explicit. The PLAYWRIGHT_DRIVER_URL env var (or per-profile
browser_connection_url) points to a running Chrome/Chromium container that
exposes the CDP WebSocket endpoint (e.g. ws://playwright-chrome:3000).
"""
from changedetectionio.pluggy_interface import hookimpl
from changedetectionio.content_fetchers.playwright import PlaywrightBaseFetcher


class fetcher(PlaywrightBaseFetcher):
    fetcher_description = "Playwright Chrome (CDP/Remote)"

    def __init__(self, proxy_override=None, custom_browser_connection_url=None, **kwargs):
        super().__init__(proxy_override=proxy_override, custom_browser_connection_url=custom_browser_connection_url, **kwargs)

        if custom_browser_connection_url:
            self.browser_connection_is_custom = True
            self.browser_connection_url = custom_browser_connection_url
        else:
            self.browser_connection_url = 'ws://playwright-chrome:3000'

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
