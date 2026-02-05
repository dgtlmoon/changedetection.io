import re
import hashlib
from changedetectionio.content_fetchers.base import Fetcher
from changedetectionio.strtobool import strtobool
from copy import deepcopy
from abc import abstractmethod
import os
from loguru import logger

SCREENSHOT_FORMAT_JPEG = 'JPEG'
SCREENSHOT_FORMAT_PNG = 'PNG'

class difference_detection_processor():
    browser_steps = None
    datastore = None
    fetcher = None
    screenshot = None
    watch = None
    xpath_data = None
    preferred_proxy = None
    screenshot_format = SCREENSHOT_FORMAT_JPEG

    def __init__(self, datastore, watch_uuid):
        self.datastore = datastore
        self.watch_uuid = watch_uuid

        # Create a stable snapshot of the watch for processing
        # Why deepcopy?
        # 1. Prevents "dict changed during iteration" errors if watch is modified during processing
        # 2. Preserves Watch object with properties (.link, .is_pdf, etc.) - can't use dict()
        # 3. Safe now: Watch.__deepcopy__() shares datastore ref (no memory leak) but copies dict data
        self.watch = deepcopy(self.datastore.data['watching'].get(watch_uuid))

        # Generic fetcher that should be extended (requests, playwright etc)
        self.fetcher = Fetcher()

    async def call_browser(self, preferred_proxy_id=None):

        from requests.structures import CaseInsensitiveDict

        url = self.watch.link

        # Protect against file:, file:/, file:// access, check the real "link" without any meta "source:" etc prepended.
        if re.search(r'^file:', url.strip(), re.IGNORECASE):
            if not strtobool(os.getenv('ALLOW_FILE_URI', 'false')):
                raise Exception(
                    "file:// type access is denied for security reasons."
                )

        # Requests, playwright, other browser via wss:// etc, fetch_extra_something
        prefer_fetch_backend = self.watch.get('fetch_backend', 'system')

        # Proxy ID "key"
        preferred_proxy_id = preferred_proxy_id if preferred_proxy_id else self.datastore.get_preferred_proxy_for_watch(
            uuid=self.watch.get('uuid'))

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
                prefer_fetch_backend = 'html_webdriver'
                custom_browser_connection_url = connection[0].get('browser_connection_url')

        # PDF should be html_requests because playwright will serve it up (so far) in a embedded page
        # @todo https://github.com/dgtlmoon/changedetection.io/issues/2019
        # @todo needs test to or a fix
        if self.watch.is_pdf:
            prefer_fetch_backend = "html_requests"

        # Grab the right kind of 'fetcher', (playwright, requests, etc)
        from changedetectionio import content_fetchers
        if hasattr(content_fetchers, prefer_fetch_backend):
            # @todo TEMPORARY HACK - SWITCH BACK TO PLAYWRIGHT FOR BROWSERSTEPS
            if prefer_fetch_backend == 'html_webdriver' and self.watch.has_browser_steps:
                # This is never supported in selenium anyway
                logger.warning(
                    "Using playwright fetcher override for possible puppeteer request in browsersteps, because puppetteer:browser steps is incomplete.")
                from changedetectionio.content_fetchers.playwright import fetcher as playwright_fetcher
                fetcher_obj = playwright_fetcher
            else:
                fetcher_obj = getattr(content_fetchers, prefer_fetch_backend)
        else:
            # What it referenced doesnt exist, Just use a default
            fetcher_obj = getattr(content_fetchers, "html_requests")

        proxy_url = None
        if preferred_proxy_id:
            # Custom browser endpoints should NOT have a proxy added
            if not prefer_fetch_backend.startswith('extra_browser_'):
                proxy_url = self.datastore.proxy_list.get(preferred_proxy_id).get('url')
                logger.debug(f"Selected proxy key '{preferred_proxy_id}' as proxy URL '{proxy_url}' for {url}")
            else:
                logger.debug("Skipping adding proxy data when custom Browser endpoint is specified. ")

        logger.debug(f"Using proxy '{proxy_url}' for {self.watch['uuid']}")

        # Now call the fetcher (playwright/requests/etc) with arguments that only a fetcher would need.
        # When browser_connection_url is None, it method should default to working out whats the best defaults (os env vars etc)
        self.fetcher = fetcher_obj(proxy_override=proxy_url,
                                   custom_browser_connection_url=custom_browser_connection_url,
                                   screenshot_format=self.screenshot_format
                                   )

        if self.watch.has_browser_steps:
            self.fetcher.browser_steps = self.watch.get('browser_steps', [])
            self.fetcher.browser_steps_screenshot_path = os.path.join(self.datastore.datastore_path, self.watch.get('uuid'))

        # Tweak the base config with the per-watch ones
        from changedetectionio.jinja2_custom import render as jinja_render
        request_headers = CaseInsensitiveDict()

        ua = self.datastore.data['settings']['requests'].get('default_ua')
        if ua and ua.get(prefer_fetch_backend):
            request_headers.update({'User-Agent': ua.get(prefer_fetch_backend)})

        request_headers.update(self.watch.get('headers', {}))
        request_headers.update(self.datastore.get_all_base_headers())
        request_headers.update(self.datastore.get_all_headers_in_textfile_for_watch(uuid=self.watch.get('uuid')))

        # https://github.com/psf/requests/issues/4525
        # Requests doesnt yet support brotli encoding, so don't put 'br' here, be totally sure that the user cannot
        # do this by accident.
        if 'Accept-Encoding' in request_headers and "br" in request_headers['Accept-Encoding']:
            request_headers['Accept-Encoding'] = request_headers['Accept-Encoding'].replace(', br', '')

        for header_name in request_headers:
            request_headers.update({header_name: jinja_render(template_str=request_headers.get(header_name))})

        timeout = self.datastore.data['settings']['requests'].get('timeout')

        request_body = self.watch.get('body')
        if request_body:
            request_body = jinja_render(template_str=self.watch.get('body'))

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
        empty_pages_are_a_change = self.datastore.data['settings']['application'].get('empty_pages_are_a_change', False)
        # All fetchers are now async
        await self.fetcher.run(
            current_include_filters=self.watch.get('include_filters'),
            empty_pages_are_a_change=empty_pages_are_a_change,
            fetch_favicon=self.watch.favicon_is_expired(),
            ignore_status_codes=ignore_status_codes,
            is_binary=is_binary,
            request_body=request_body,
            request_headers=request_headers,
            request_method=request_method,
            screenshot_format=self.screenshot_format,
            timeout=timeout,
            url=url,
            watch_uuid=self.watch_uuid,
        )

        # @todo .quit here could go on close object, so we can run JS if change-detected
        await self.fetcher.quit(watch=self.watch)

        # After init, call run_changedetection() which will do the actual change-detection

    def get_extra_watch_config(self, filename):
        """
        Read processor-specific JSON config file from watch data directory.

        Args:
            filename: Name of JSON file (e.g., "visual_ssim_score.json")

        Returns:
            dict: Parsed JSON data, or empty dict if file doesn't exist
        """
        import json
        import os

        watch = self.datastore.data['watching'].get(self.watch_uuid)
        watch_data_dir = watch.watch_data_dir

        if not watch_data_dir:
            return {}

        filepath = os.path.join(watch_data_dir, filename)

        if not os.path.isfile(filepath):
            return {}

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to read extra watch config {filename}: {e}")
            return {}

    def update_extra_watch_config(self, filename, data, merge=True):
        """
        Write processor-specific JSON config file to watch data directory.

        Args:
            filename: Name of JSON file (e.g., "visual_ssim_score.json")
            data: Dictionary to serialize as JSON
            merge: If True, merge with existing data; if False, overwrite completely
        """
        import json
        import os

        watch = self.datastore.data['watching'].get(self.watch_uuid)
        watch_data_dir = watch.watch_data_dir

        if not watch_data_dir:
            logger.warning(f"Cannot save extra watch config {filename}: no watch_data_dir")
            return

        # Ensure directory exists
        watch.ensure_data_dir_exists()

        filepath = os.path.join(watch_data_dir, filename)

        try:
            # If merge is enabled, read existing data first
            existing_data = {}
            if merge and os.path.isfile(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        existing_data = json.load(f)
                except (json.JSONDecodeError, IOError) as e:
                    logger.warning(f"Failed to read existing config for merge: {e}")

            # Merge new data with existing
            if merge:
                existing_data.update(data)
                data_to_save = existing_data
            else:
                data_to_save = data

            # Write the data
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data_to_save, f, indent=2)
        except IOError as e:
            logger.error(f"Failed to write extra watch config {filename}: {e}")

    @abstractmethod
    def run_changedetection(self, watch):
        update_obj = {'last_notification_error': False, 'last_error': False}
        some_data = 'xxxxx'
        update_obj["previous_md5"] = hashlib.md5(some_data.encode('utf-8')).hexdigest()
        changed_detected = False
        return changed_detected, update_obj, ''.encode('utf-8')
