
import hashlib
import os
import re
import urllib3
from . import difference_detection_processor
from copy import deepcopy
from .. import fetchers

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

name = 'Re-stock detection for single product pages'
description = 'Detects if the product goes back to in-stock'

class perform_site_check(difference_detection_processor):
    screenshot = None
    xpath_data = None

    def __init__(self, *args, datastore, **kwargs):
        super().__init__(*args, **kwargs)
        self.datastore = datastore

    def run(self, uuid, skip_when_checksum_same=True):

        # DeepCopy so we can be sure we don't accidently change anything by reference
        watch = deepcopy(self.datastore.data['watching'].get(uuid))

        if not watch:
            raise Exception("Watch no longer exists.")

        # Protect against file:// access
        if re.search(r'^file', watch.get('url', ''), re.IGNORECASE) and not os.getenv('ALLOW_FILE_URI', False):
            raise Exception(
                "file:// type access is denied for security reasons."
            )

        # Unset any existing notification error
        update_obj = {'last_notification_error': False, 'last_error': False}
        extra_headers = watch.get('headers', [])

        # Tweak the base config with the per-watch ones
        request_headers = deepcopy(self.datastore.data['settings']['headers'])
        request_headers.update(extra_headers)

        # https://github.com/psf/requests/issues/4525
        # Requests doesnt yet support brotli encoding, so don't put 'br' here, be totally sure that the user cannot
        # do this by accident.
        if 'Accept-Encoding' in request_headers and "br" in request_headers['Accept-Encoding']:
            request_headers['Accept-Encoding'] = request_headers['Accept-Encoding'].replace(', br', '')

        timeout = self.datastore.data['settings']['requests'].get('timeout')

        url = watch.link

        request_body = self.datastore.data['watching'][uuid].get('body')
        request_method = self.datastore.data['watching'][uuid].get('method')
        ignore_status_codes = self.datastore.data['watching'][uuid].get('ignore_status_codes', False)

        # Pluggable content fetcher
        prefer_backend = watch.get_fetch_backend
        if not prefer_backend or prefer_backend == 'system':
            prefer_backend = self.datastore.data['settings']['application']['fetch_backend']

        if prefer_backend == 'html_webdriver':
            preferred_fetcher = fetchers.html_webdriver
        else:
            from ..fetchers import html_requests
            preferred_fetcher = html_requests


        proxy_id = self.datastore.get_preferred_proxy_for_watch(uuid=uuid)
        proxy_url = None
        if proxy_id:
            proxy_url = self.datastore.proxy_list.get(proxy_id).get('url')
            print("UUID {} Using proxy {}".format(uuid, proxy_url))

        fetcher = preferred_fetcher(proxy_override=proxy_url)

        # Configurable per-watch or global extra delay before extracting text (for webDriver types)
        system_webdriver_delay = self.datastore.data['settings']['application'].get('webdriver_delay', None)
        if watch['webdriver_delay'] is not None:
            fetcher.render_extract_delay = watch.get('webdriver_delay')
        elif system_webdriver_delay is not None:
            fetcher.render_extract_delay = system_webdriver_delay

        # Could be removed if requests/plaintext could also return some info?
        if prefer_backend != 'html_webdriver':
            raise Exception("Re-stock detection requires Chrome or compatible webdriver/playwright fetcher to work")

        if watch.get('webdriver_js_execute_code') is not None and watch.get('webdriver_js_execute_code').strip():
            fetcher.webdriver_js_execute_code = watch.get('webdriver_js_execute_code')

        fetcher.run(url, timeout, request_headers, request_body, request_method, ignore_status_codes, watch.get('include_filters'))
        fetcher.quit()

        self.screenshot = fetcher.screenshot
        self.xpath_data = fetcher.xpath_data

        # Track the content type
        update_obj['content_type'] = fetcher.headers.get('Content-Type', '')
        update_obj["last_check_status"] = fetcher.get_last_status_code()

        # Main detection method
        fetched_md5 = None
        if fetcher.instock_data:
            fetched_md5 = hashlib.md5(fetcher.instock_data.encode('utf-8')).hexdigest()
            # 'Possibly in stock' comes from stock-not-in-stock.js when no string found above the fold.
            update_obj["in_stock"] = True if fetcher.instock_data == 'Possibly in stock' else False


        # The main thing that all this at the moment comes down to :)
        changed_detected = False

        if watch.get('previous_md5') and watch.get('previous_md5') != fetched_md5:
            # Yes if we only care about it going to instock, AND we are in stock
            if watch.get('in_stock_only') and update_obj["in_stock"]:
                changed_detected = True

            if not watch.get('in_stock_only'):
                # All cases
                changed_detected = True

        # Always record the new checksum
        update_obj["previous_md5"] = fetched_md5

        return changed_detected, update_obj, fetcher.instock_data.encode('utf-8')
