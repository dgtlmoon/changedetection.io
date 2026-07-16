"""
Debug/test content fetcher.

Does NOT fetch anything - it echoes the resolved-and-injected browser state (backend name +
FetcherConfig) as JSON into `self.content`. That lets pytest exercise the *entire* browser-config
pipeline end-to-end with a real watch check - resolve_content_fetcher -> engine selection ->
FetcherConfig injection -> fetch - and assert on the stored snapshot, all without a real browser.

Registered as a built-in fetcher but hidden from the UI browser lists (name prefixed 'html_debug').
"""
import json

from changedetectionio.content_fetchers.base import Fetcher


class fetcher(Fetcher):
    fetcher_description = "Debug test browser (echoes resolved browser config)"

    # Advertise every capability so all FetcherConfig fields are exercisable through it.
    supports_browser_steps = True
    supports_screenshots = True
    supports_xpath_element_data = True
    supports_request_blocking = True
    supports_browser_type = True
    supports_delete_created_files = True

    async def run(self,
                  url=None,
                  request_headers=None,
                  request_body=None,
                  request_method=None,
                  **kwargs):
        bc = getattr(self, 'browser_config', None)
        payload = {
            'debug_test_browser': True,
            'backend_name': getattr(self, 'backend_name', None),
            'url': url,
            'browser_config': bc.model_dump() if (bc is not None and hasattr(bc, 'model_dump')) else bc,
            'request_headers': {k: v for k, v in (request_headers or {}).items()},
        }
        self.content = json.dumps(payload, indent=2, sort_keys=True, default=str)
        self.raw_content = self.content.encode('utf-8')
        self.status_code = 200
        self.headers = {'content-type': 'application/json'}
        self.screenshot = None
        self.xpath_data = {'xpath_data': [], 'browser_width': 0}
        self.instock_data = None


class DebugTestBrowserFetcherPlugin:
    """Registers the debug test fetcher as a built-in plugin."""

    def register_content_fetcher(self):
        return ('html_debug_test_browser', fetcher)


debug_test_browser_plugin = DebugTestBrowserFetcherPlugin()
