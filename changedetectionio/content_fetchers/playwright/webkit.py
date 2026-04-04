"""
Playwright WebKit fetcher — launches a local WebKit (Safari-engine) browser.

No external browser container is required.  Playwright must be installed
with WebKit browsers: ``playwright install webkit``.

Note: ``page.request_gc()`` is Chromium-specific and is silently skipped
on WebKit — handled transparently by ``_safe_request_gc()`` in the base package.
"""
from changedetectionio.pluggy_interface import hookimpl
from changedetectionio.content_fetchers.playwright import PlaywrightBaseFetcher


class fetcher(PlaywrightBaseFetcher):
    fetcher_description = "Playwright WebKit/Safari (local)"

    async def _connect_browser(self, p):
        launch_kwargs = {'headless': True}
        if self.proxy:
            launch_kwargs['proxy'] = self.proxy
        return await p.webkit.launch(**launch_kwargs)


class PlaywrightWebKitPlugin:
    @hookimpl
    def register_content_fetcher(self):
        return ('playwright_webkit', fetcher)


webkit_plugin = PlaywrightWebKitPlugin()
