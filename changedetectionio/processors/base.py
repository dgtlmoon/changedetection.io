import asyncio
import re
import hashlib

from changedetectionio.browser_steps.browser_steps import browser_steps_get_valid_steps
from changedetectionio.content_fetchers.base import Fetcher
from changedetectionio.strtobool import strtobool
from changedetectionio.validate_url import is_private_hostname
from copy import deepcopy
from abc import abstractmethod
import os
from urllib.parse import urlparse
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
    preferred_proxy_override = None   # Set externally to force a specific proxy (e.g. proxy checker)
    screenshot_format = SCREENSHOT_FORMAT_JPEG
    last_raw_content_checksum = None

    def __init__(self, datastore, watch_uuid):
        self.datastore = datastore
        self.watch_uuid = watch_uuid

        # Create a stable snapshot of the watch for processing
        # Why deepcopy?
        # 1. Prevents "dict changed during iteration" errors if watch is modified during processing
        # 2. Preserves Watch object with properties (.link, .is_pdf, etc.) - can't use dict()
        # 3. Safe now: Watch.__deepcopy__() shares datastore ref (no memory leak) but copies dict data
        self.watch = deepcopy(self.datastore.data['watching'].get(watch_uuid))
        if self.watch is None:
            raise KeyError(f"Watch UUID {watch_uuid} not found in datastore (deleted before processing?)")

        # Generic fetcher that should be extended (requests, playwright etc)
        self.fetcher = Fetcher()

        # Load the last raw content checksum from file
        self.read_last_raw_content_checksum()

    def update_last_raw_content_checksum(self, checksum):
        """
        Save the raw content MD5 checksum to file.
        This is used for skip logic - avoid reprocessing if raw HTML unchanged.
        """
        if not checksum:
            return

        watch = self.datastore.data['watching'].get(self.watch_uuid)
        if not watch:
            return

        data_dir = watch.data_dir
        if not data_dir:
            return

        watch.ensure_data_dir_exists()
        checksum_file = os.path.join(data_dir, 'last-checksum.txt')

        try:
            with open(checksum_file, 'w', encoding='utf-8') as f:
                f.write(checksum)
            self.last_raw_content_checksum = checksum
        except IOError as e:
            logger.warning(f"Failed to write checksum file for {self.watch_uuid}: {e}")

    def read_last_raw_content_checksum(self):
        """
        Read the last raw content MD5 checksum from file.
        Returns None if file doesn't exist (first run) or can't be read.
        """
        watch = self.datastore.data['watching'].get(self.watch_uuid)
        if not watch:
            self.last_raw_content_checksum = None
            return

        data_dir = watch.data_dir
        if not data_dir:
            self.last_raw_content_checksum = None
            return

        checksum_file = os.path.join(data_dir, 'last-checksum.txt')

        if not os.path.isfile(checksum_file):
            self.last_raw_content_checksum = None
            return

        try:
            with open(checksum_file, 'r', encoding='utf-8') as f:
                self.last_raw_content_checksum = f.read().strip()
        except IOError as e:
            logger.warning(f"Failed to read checksum file for {self.watch_uuid}: {e}")
            self.last_raw_content_checksum = None


    async def validate_iana_url(self):
        """Pre-flight SSRF check — runs DNS lookup in executor to avoid blocking the event loop.
        Covers all fetchers (requests, playwright, puppeteer, plugins) since every fetch goes
        through call_browser().
        """
        if strtobool(os.getenv('ALLOW_IANA_RESTRICTED_ADDRESSES', 'false')):
            return
        parsed = urlparse(self.watch.link)
        if not parsed.hostname:
            return
        loop = asyncio.get_running_loop()
        if await loop.run_in_executor(None, is_private_hostname, parsed.hostname):
            raise Exception(
                f"Fetch blocked: '{self.watch.link}' resolves to a private/reserved IP address. "
                f"Set ALLOW_IANA_RESTRICTED_ADDRESSES=true to allow."
            )

    async def call_browser(self):

        from requests.structures import CaseInsensitiveDict
        from changedetectionio.model.browser_profile import resolve_browser_profile, BUILTIN_REQUESTS

        url = self.watch.link

        # Protect against file:, file:/, file:// access
        if re.search(r'^file:', url.strip(), re.IGNORECASE):
            if not strtobool(os.getenv('ALLOW_FILE_URI', 'false')):
                raise Exception("file:// type access is denied for security reasons.")

        await self.validate_iana_url()

        # Resolve the full browser profile for this watch (watch → tag → global → built-in)
        profile = resolve_browser_profile(self.watch, self.datastore)

        # PDFs always use the requests fetcher — browsers render them in an embedded viewer
        # @todo https://github.com/dgtlmoon/changedetection.io/issues/2019
        if self.watch.is_pdf:
            profile = BUILTIN_REQUESTS

        # Resolve proxy for the target URL fetch.
        # Note: browser_connection_url is the WebSocket endpoint to reach the remote browser,
        # which is separate from the proxy used by the browser to fetch target pages.
        proxy_url = self.datastore.get_proxy_url_for_watch(self.watch.get('uuid'), override_id=self.preferred_proxy_override)
        if proxy_url:
            logger.debug(f"Proxy '{proxy_url}' for {url}")

        logger.debug(f"BrowserProfile '{profile.get_machine_name()}' (fetcher={profile.fetch_backend}) for watch {self.watch['uuid']}")

        # Select the fetcher class
        from changedetectionio import content_fetchers
        fetcher_class_name = profile.get_fetcher_class_name()

        fetcher_obj = content_fetchers.get_fetcher(fetcher_class_name)
        if fetcher_obj is None:
            logger.warning(f"Fetcher '{fetcher_class_name}' not found, falling back to requests")
            fetcher_obj = content_fetchers.get_fetcher('requests')
        elif self.watch.has_browser_steps and not getattr(fetcher_obj, 'supports_browser_steps', False):
            # Browser steps require Playwright — override if the resolved fetcher doesn't support them
            logger.warning(f"Fetcher '{fetcher_class_name}' does not support browser steps, overriding to Playwright")
            fetcher_obj = content_fetchers.get_fetcher('playwright')

        self.fetcher = fetcher_obj(
            proxy_override=proxy_url,
            custom_browser_connection_url=profile.browser_connection_url,
            screenshot_format=self.screenshot_format,
            # BrowserProfile fields — browser fetchers use these; html_requests ignores them
            viewport_width=profile.viewport_width,
            viewport_height=profile.viewport_height,
            block_images=profile.block_images,
            block_fonts=profile.block_fonts,
            profile_user_agent=profile.user_agent,
            ignore_https_errors=profile.ignore_https_errors,
            locale=profile.locale,
            service_workers=profile.service_workers,
            extra_delay=profile.extra_delay,
        )

        if self.watch.has_browser_steps:
            self.fetcher.browser_steps = browser_steps_get_valid_steps(self.watch.get('browser_steps', []))
            self.fetcher.browser_steps_screenshot_path = os.path.join(self.datastore.datastore_path, self.watch.get('uuid'))

        # Tweak the base config with the per-watch ones
        from changedetectionio.jinja2_custom import render as jinja_render
        request_headers = CaseInsensitiveDict()

        ua = self.datastore.data['settings']['requests'].get('default_ua')
        ua_key = getattr(fetcher_obj, 'ua_settings_key', fetcher_class_name)
        if ua and ua.get(ua_key):
            request_headers.update({'User-Agent': ua.get(ua_key)})

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
        self.fetcher.disk_cleanup_after_fetch()

        # Sanitize lone surrogates - these can appear when servers return malformed/mixed-encoding
        # content that gets decoded into surrogate characters (e.g. \udcad). Without this,
        # encode('utf-8') raises UnicodeEncodeError downstream in checksums, diffs, file writes, etc.
        # Covers all fetchers (requests, playwright, puppeteer, selenium) in one place.
        # Also note: By this point we SHOULD know the original encoding so it can safely convert to utf-8 for the rest of the app.
        # See: https://github.com/dgtlmoon/changedetection.io/issues/3952

        if self.fetcher.content and isinstance(self.fetcher.content, str):
            self.fetcher.content = self.fetcher.content.encode('utf-8', errors='replace').decode('utf-8')

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
        data_dir = watch.data_dir

        if not data_dir:
            return {}

        filepath = os.path.join(data_dir, filename)

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
        data_dir = watch.data_dir

        if not data_dir:
            logger.warning(f"Cannot save extra watch config {filename}: no data_dir")
            return

        # Ensure directory exists
        watch.ensure_data_dir_exists()

        filepath = os.path.join(data_dir, filename)

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

    def get_raw_document_checksum(self):
        checksum = None

        if self.fetcher.content:
            checksum = hashlib.md5(self.fetcher.content.encode('utf-8')).hexdigest()

        return checksum

    @abstractmethod
    def run_changedetection(self, watch, force_reprocess=False):
        update_obj = {'last_notification_error': False, 'last_error': False}
        some_data = 'xxxxx'
        update_obj["previous_md5"] = hashlib.md5(some_data.encode('utf-8')).hexdigest()
        changed_detected = False
        return changed_detected, update_obj, ''.encode('utf-8')
