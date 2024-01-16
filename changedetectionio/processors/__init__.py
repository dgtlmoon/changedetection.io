from abc import abstractmethod
import os
import hashlib
import re
from changedetectionio import content_fetcher
from copy import deepcopy
from distutils.util import strtobool
from loguru import logger

class difference_detection_processor():

    browser_steps = None
    datastore = None
    fetcher = None
    screenshot = None
    watch = None
    xpath_data = None

    def __init__(self, *args, datastore, watch_uuid, **kwargs):
        super().__init__(*args, **kwargs)
        self.datastore = datastore
        self.watch = deepcopy(self.datastore.data['watching'].get(watch_uuid))

    def call_browser(self):

        # Protect against file:// access
        if re.search(r'^file://', self.watch.get('url', '').strip(), re.IGNORECASE):
            if not strtobool(os.getenv('ALLOW_FILE_URI', 'false')):
                raise Exception(
                    "file:// type access is denied for security reasons."
                )

        url = self.watch.link

        # Requests, playwright, other browser via wss:// etc, fetch_extra_something
        prefer_fetch_backend = self.watch.get('fetch_backend', 'system')

        # Proxy ID "key"
        preferred_proxy_id = self.datastore.get_preferred_proxy_for_watch(uuid=self.watch.get('uuid'))

        # Pluggable content self.fetcher
        if not prefer_fetch_backend or prefer_fetch_backend == 'system':
            prefer_fetch_backend = self.datastore.data['settings']['application'].get('fetch_backend')

        # In the case that the preferred fetcher was a browser config with custom connection URL..
        # @todo - on save watch, if its extra_browser_ then it should be obvious it will use playwright (like if its requests now..)
        custom_browser_connection_url = None
        if prefer_fetch_backend.startswith('extra_browser_'):
            (t, key) = prefer_fetch_backend.split('extra_browser_')
            connection = list(
                filter(lambda s: (s['browser_name'] == key), self.datastore.data['settings']['requests'].get('extra_browsers', [])))
            if connection:
                prefer_fetch_backend = 'base_html_playwright'
                custom_browser_connection_url = connection[0].get('browser_connection_url')

        # PDF should be html_requests because playwright will serve it up (so far) in a embedded page
        # @todo https://github.com/dgtlmoon/changedetection.io/issues/2019
        # @todo needs test to or a fix
        if self.watch.is_pdf:
           prefer_fetch_backend = "html_requests"

        # Grab the right kind of 'fetcher', (playwright, requests, etc)
        if hasattr(content_fetcher, prefer_fetch_backend):
            fetcher_obj = getattr(content_fetcher, prefer_fetch_backend)
        else:
            # If the klass doesnt exist, just use a default
            fetcher_obj = getattr(content_fetcher, "html_requests")


        proxy_url = None
        if preferred_proxy_id:
            proxy_url = self.datastore.proxy_list.get(preferred_proxy_id).get('url')
            logger.debug(f"Selected proxy key '{preferred_proxy_id}' as proxy URL '{proxy_url}' for {url}")

        # Now call the fetcher (playwright/requests/etc) with arguments that only a fetcher would need.
        # When browser_connection_url is None, it method should default to working out whats the best defaults (os env vars etc)
        self.fetcher = fetcher_obj(proxy_override=proxy_url,
                                   custom_browser_connection_url=custom_browser_connection_url
                                   )

        if self.watch.has_browser_steps:
            self.fetcher.browser_steps = self.watch.get('browser_steps', [])
            self.fetcher.browser_steps_screenshot_path = os.path.join(self.datastore.datastore_path, self.watch.get('uuid'))

        # Tweak the base config with the per-watch ones
        request_headers = self.watch.get('headers', [])
        request_headers.update(self.datastore.get_all_base_headers())
        request_headers.update(self.datastore.get_all_headers_in_textfile_for_watch(uuid=self.watch.get('uuid')))

        # https://github.com/psf/requests/issues/4525
        # Requests doesnt yet support brotli encoding, so don't put 'br' here, be totally sure that the user cannot
        # do this by accident.
        if 'Accept-Encoding' in request_headers and "br" in request_headers['Accept-Encoding']:
            request_headers['Accept-Encoding'] = request_headers['Accept-Encoding'].replace(', br', '')

        timeout = self.datastore.data['settings']['requests'].get('timeout')

        request_body = self.watch.get('body')
        request_method = self.watch.get('method')
        ignore_status_codes = self.watch.get('ignore_status_codes', False)

        # Configurable per-watch or global extra delay before extracting text (for webDriver types)
        system_webdriver_delay = self.datastore.data['settings']['application'].get('webdriver_delay', None)
        if self.watch.get('webdriver_delay'):
            self.fetcher.render_extract_delay = self.watch.get('webdriver_delay')
        elif system_webdriver_delay is not None:
            self.fetcher.render_extract_delay = system_webdriver_delay

        if self.watch.get('webdriver_js_execute_code') is not None and self.watch.get('webdriver_js_execute_code').strip():
            self.fetcher.webdriver_js_execute_code = self.watch.get('webdriver_js_execute_code')

        # Requests for PDF's, images etc should be passwd the is_binary flag
        is_binary = self.watch.is_pdf

        # And here we go! call the right browser with browser-specific settings
        self.fetcher.run(url, timeout, request_headers, request_body, request_method, ignore_status_codes, self.watch.get('include_filters'),
                    is_binary=is_binary)

        #@todo .quit here could go on close object, so we can run JS if change-detected
        self.fetcher.quit()

        # After init, call run_changedetection() which will do the actual change-detection

    @abstractmethod
    def run_changedetection(self, uuid, skip_when_checksum_same=True):
        update_obj = {'last_notification_error': False, 'last_error': False}
        some_data = 'xxxxx'
        update_obj["previous_md5"] = hashlib.md5(some_data.encode('utf-8')).hexdigest()
        changed_detected = False
        return changed_detected, update_obj, ''.encode('utf-8')


def available_processors():
    from . import restock_diff, text_json_diff
    x=[('text_json_diff', text_json_diff.name), ('restock_diff', restock_diff.name)]
    # @todo Make this smarter with introspection of sorts.
    return x
