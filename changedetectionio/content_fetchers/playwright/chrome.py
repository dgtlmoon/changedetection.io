"""
Playwright Chrome fetcher — launches a local Chromium browser directly.

No external browser container is required.  Playwright must be installed
with Chromium browsers: ``playwright install chromium``.
"""
from changedetectionio.pluggy_interface import hookimpl
from changedetectionio.content_fetchers.playwright import PlaywrightBaseFetcher


class fetcher(PlaywrightBaseFetcher):
    fetcher_description = "Playwright Chrome (local)"

    async def _connect_browser(self, p):
        launch_kwargs = {'headless': True}
        if self.proxy:
            launch_kwargs['proxy'] = self.proxy
        return await p.chromium.launch(**launch_kwargs)


class PlaywrightChromePlugin:
    @hookimpl
    def register_content_fetcher(self):
        return ('playwright_chrome', fetcher)


chrome_plugin = PlaywrightChromePlugin()
