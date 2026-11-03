"""The fetcher: gets the page from a scraping API with this small JSON contract.

    POST {Scraping API URL}            header X-Api-Key: {API key}
    {"url": "...", "headers": {...}, "screenshot": true, "timeout": 60}

    200 OK
    {"status_code": 200,               the site's own answer
     "content": "<html>...",
     "content_type": "text/html",
     "screenshot": "iVBORw0..."}       base64 PNG, or null

Most scraping services take something close to this, adapt _fetch() to the one you use.
"""
import asyncio

from changedetectionio.plugin_api import Fetcher, Non200ErrorCodeReceived


class fetcher(Fetcher):
    fetcher_description = 'Fallback fetcher (example plugin)'
    # It sends back a screenshot (when "Ask for a screenshot" is on), so it's shown and saved
    supports_screenshots = True

    def __init__(self, proxy_override=None, custom_browser_connection_url=None, **kwargs):
        # proxy_override is ignored, a scraping API fetches through its own network
        super().__init__(**kwargs)

    async def run(self, url=None, timeout=None, request_headers=None, ignore_status_codes=False, **kwargs):
        # requests is blocking, keep it off the event loop
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: self._fetch(url, timeout, request_headers, ignore_status_codes))

    def _fetch(self, url, timeout, request_headers, ignore_status_codes):
        import base64
        import requests
        from . import get_settings

        settings = get_settings()
        api_url = (settings.get('fallback_fetcher_url') or '').strip()
        if not api_url:
            raise Exception("The fallback fetcher isn't set up, add the scraping API URL in Settings > Fallback fetcher")
        timeout = timeout or 60

        r = requests.post(api_url, timeout=timeout + 30,  # the service's own overhead comes on top
                          headers={'X-Api-Key': settings.get('fallback_fetcher_key') or ''},
                          json={'url': url, 'headers': dict(request_headers or {}), 'timeout': timeout,
                                'screenshot': bool(settings.get('fallback_fetcher_screenshot', True))})
        if not r.ok:
            raise Exception(f"Scraping API returned HTTP {r.status_code}")
        try:
            reply = r.json()
        except ValueError:
            raise Exception("Scraping API didn't answer with JSON")

        status_code = int(reply.get('status_code') or 200)
        content = reply.get('content') or ''
        # The site's own answer, the same as the other fetchers
        if status_code != 200 and not ignore_status_codes:
            raise Non200ErrorCodeReceived(url=url, status_code=status_code, page_html=content)

        # What a fetcher must set for the processor
        self.status_code = status_code
        self.headers = {'content-type': reply.get('content_type') or 'text/html'}
        self.content = content
        self.raw_content = content.encode('utf-8')
        # Saved as last-screenshot.png
        self.screenshot = base64.b64decode(reply['screenshot']) if reply.get('screenshot') else None

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
