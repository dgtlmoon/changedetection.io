"""
html_playwright_builtin - launches a LOCAL Playwright browser (using the installed `playwright`
library) instead of connecting to a remote CDP endpoint like the default html_webdriver.

It subclasses the highly-tuned playwright.fetcher and overrides only the _get_browser() seam,
so the entire run() body - browser steps, screenshots, xpath, stitching - is shared. Everything
stays async (runs on the worker's own event loop, never the UI loop).

Only registered when the playwright library is importable (see register_builtin_fetchers).
Cross-platform temp isolation: a per-fetch temp dir with best-effort cleanup (tolerates the
Windows file-lock case). Browser processes are separate OS processes reclaimed on close().
"""
import shutil
import tempfile

from loguru import logger

from changedetectionio.content_fetchers.playwright import fetcher as playwright_fetcher


class fetcher(playwright_fetcher):
    fetcher_description = "Playwright (local library)"

    local_launch = True
    # A local launch can pick the engine and owns its temp files.
    supports_browser_type = True
    supports_delete_created_files = True

    def __init__(self, proxy_override=None, custom_browser_connection_url=None, **kwargs):
        super().__init__(proxy_override=proxy_override,
                         custom_browser_connection_url=custom_browser_connection_url, **kwargs)
        self._local_tmp_dir = None

    async def _get_browser(self, browser_type):
        # Dedicated per-fetch dir; tempfile respects TMPDIR/%TEMP% so it's cross-platform.
        self._local_tmp_dir = tempfile.mkdtemp(prefix='cdio-playwright-')
        return await browser_type.launch(headless=True, downloads_path=self._local_tmp_dir)

    async def quit(self, watch=None):
        # quit() is the fetcher lifecycle-cleanup hook (called by the worker as a guaranteed
        # safety net after every fetch, success or error) - so temp-file removal belongs here.
        try:
            await super().quit(watch=watch)
        finally:
            bc = getattr(self, 'browser_config', None)
            delete = True if bc is None else bool(getattr(bc, 'delete_created_files', True))
            if self._local_tmp_dir and delete:
                # ignore_errors tolerates Windows file locks / an already-removed dir.
                shutil.rmtree(self._local_tmp_dir, ignore_errors=True)
            self._local_tmp_dir = None


class PlaywrightBuiltinFetcherPlugin:
    def register_content_fetcher(self):
        return ('html_playwright_builtin', fetcher)


playwright_builtin_plugin = PlaywrightBuiltinFetcherPlugin()
