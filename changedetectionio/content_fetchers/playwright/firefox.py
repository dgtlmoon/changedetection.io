"""
Playwright Firefox fetcher — launches a local Firefox browser directly.

No external browser container is required.  Playwright must be installed
with Firefox browsers: ``playwright install firefox``.

Note: ``page.request_gc()`` is Chromium-specific and is silently skipped
on Firefox — this is handled transparently by ``_safe_request_gc()`` in
the base package.
"""
from changedetectionio.pluggy_interface import hookimpl
from changedetectionio.content_fetchers.playwright import PlaywrightBaseFetcher


class fetcher(PlaywrightBaseFetcher):
    fetcher_description = "Playwright Firefox (local)"

    status_icon = {'filename': 'firefox-icon.svg', 'alt': 'Using Firefox', 'title': 'Using Firefox'}

    async def _connect_browser(self, p):
        launch_kwargs = {'headless': True}
        if self.proxy:
            launch_kwargs['proxy'] = self.proxy
        return await p.firefox.launch(**launch_kwargs)


class PlaywrightFirefoxPlugin:
    @hookimpl
    def register_content_fetcher(self):
        return ('playwright_firefox', fetcher)


firefox_plugin = PlaywrightFirefoxPlugin()
