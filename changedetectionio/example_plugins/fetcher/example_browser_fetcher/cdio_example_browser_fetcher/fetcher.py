import asyncio
from urllib.parse import quote

from changedetectionio.plugin_api import Fetcher, load_plugin_settings


class fetcher(Fetcher):
    fetcher_description = 'Example browser fetcher'

    def __init__(self, proxy_override=None, custom_browser_connection_url=None, **kwargs):
        super().__init__(**kwargs)

    async def run(self, url=None, timeout=None, request_headers=None, **kwargs):
        # requests is blocking, keep it off the event loop
        await asyncio.get_event_loop().run_in_executor(None, lambda: self._fetch(url, timeout, request_headers))

    def _fetch(self, url, timeout, request_headers):
        import requests
        from . import PLUGIN_ID, datastore

        settings = load_plugin_settings(datastore.datastore_path, PLUGIN_ID) if datastore else {}
        api_url = (settings.get('example_browser_fetcher_url') or '').strip()
        if '{url}' not in api_url:
            raise Exception("Example browser fetcher isn't set up, add an API URL with {url} in Settings")

        headers = dict(request_headers or {})
        if settings.get('example_browser_fetcher_key'):
            headers['X-Api-Key'] = settings['example_browser_fetcher_key']

        r = requests.get(api_url.replace('{url}', quote(url, safe='')), headers=headers, timeout=timeout or 60)
        if not r.ok:
            raise Exception(f"Example browser fetcher API returned HTTP {r.status_code}")

        # What a fetcher must set for the processor
        self.status_code = r.status_code
        self.headers = dict(r.headers)
        self.content = r.text
        self.raw_content = r.content

    async def quit(self, watch=None):
        pass

    def get_error(self):
        return self.error

    def get_last_status_code(self):
        return self.status_code

    def screenshot_step(self, step_n):
        return None

    def is_ready(self):
        return True
