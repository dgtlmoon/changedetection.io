from . import Fetcher
import os
import time
import requests


# Exploit the debugging API to get screenshot and HTML without needing playwright
# https://www.browserless.io/docs/scrape#debugging

class fetcher(Fetcher):
    fetcher_description = "Browserless Chrome/Javascript via '{}'".format(os.getenv("BROWSERLESS_DRIVER_URL"))

    command_executor = ''
    proxy = None

    def __init__(self, proxy_override=None, command_executor=None):
        super().__init__()

        # @todo proxy

    def run(self,
            url,
            timeout,
            request_headers,
            request_body,
            request_method,
            ignore_status_codes=False,
            current_include_filters=None,
            is_binary=False):

        import json
        r = requests.request(method='POST',
                             data=json.dumps({
                                 "url": url,
                                 "elements": [],
                                 "debug": {
                                     "screenshot": True,
                                     "console": False,
                                     "network": True,
                                     "cookies": False,
                                     "html": True
                                 }
                             }),
                             url=os.getenv("BROWSERLESS_DRIVER_URL"),
                             headers={'Content-Type': 'application/json'},
                             timeout=timeout,
                             #proxies=proxies,
                             verify=False)

        if r.status_code == 200:
            # the basic request to browserless was OK, but how was the internal request to the site?
            result = r.json()
            self.status_code = result['debug']['network']['inbound'][000]['status']
            self.content = result['debug']['html']

            self.headers = {}
            if result['debug'].get('screenshot'):
                import base64
                self.screenshot = base64.b64decode(result['debug']['screenshot'])


    def is_ready(self):
        # Try ping?
        return os.getenv("BROWSERLESS_DRIVER_URL", False)