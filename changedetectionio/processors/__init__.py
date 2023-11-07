from abc import abstractmethod
import os
import hashlib

from changedetectionio import content_fetcher

class difference_detection_processor():

    datastore = None
    fetcher = None
    screenshot = None
    xpath_data = None
    browser_steps = None

    def __init__(self, *args, datastore, watch_uuid, **kwargs):
        super().__init__(*args, **kwargs)
        self.datastore = datastore

        watch = self.datastore.data['watching'].get(watch_uuid)
        url = watch.link

        # Requests, playwright, other browser via wss:// etc, fetch_extra_something
        prefer_fetch_backend = watch.get('fetch_backend', 'system')

        # Proxy ID "key"
        preferred_proxy_id = self.datastore.get_preferred_proxy_for_watch(uuid=watch_uuid)

        # Pluggable content self.fetcher
        if not prefer_fetch_backend or prefer_fetch_backend == 'system':
            prefer_fetch_backend = self.datastore.data['settings']['application'].get('fetch_backend')

        # Grab the right kind of 'fetcher', (playwright, requests, etc)
        if hasattr(content_fetcher, prefer_fetch_backend):
            fetcher_obj = getattr(content_fetcher, prefer_fetch_backend)
        else:
            # If the klass doesnt exist, just use a default
            fetcher_obj = getattr(content_fetcher, "html_requests")


        proxy_url = None
        if preferred_proxy_id:
            proxy_url = self.datastore.proxy_list.get(preferred_proxy_id).get('url')
            print(f"Using proxy Key: {preferred_proxy_id} as Proxy URL {proxy_url}")

        # Now call the fetcher (playwright/requests/etc) with arguments that only a fetcher would need.
        self.fetcher = fetcher_obj(proxy_override=proxy_url,
                                   #browser_url_extra/configurable browser url=...
                                   )

        if watch.has_browser_steps:
            self.fetcher.browser_steps = watch.get('browser_steps', [])
            self.fetcher.browser_steps_screenshot_path = os.path.join(self.datastore.datastore_path, watch_uuid)

        # Tweak the base config with the per-watch ones
        request_headers = watch.get('headers', [])
        request_headers.update(self.datastore.get_all_base_headers())
        request_headers.update(self.datastore.get_all_headers_in_textfile_for_watch(uuid=watch_uuid))

        # https://github.com/psf/requests/issues/4525
        # Requests doesnt yet support brotli encoding, so don't put 'br' here, be totally sure that the user cannot
        # do this by accident.
        if 'Accept-Encoding' in request_headers and "br" in request_headers['Accept-Encoding']:
            request_headers['Accept-Encoding'] = request_headers['Accept-Encoding'].replace(', br', '')

        timeout = self.datastore.data['settings']['requests'].get('timeout')

        request_body = watch.get('body')
        request_method = watch.get('method')
        ignore_status_codes = watch.get('ignore_status_codes', False)

        # Configurable per-watch or global extra delay before extracting text (for webDriver types)
        system_webdriver_delay = self.datastore.data['settings']['application'].get('webdriver_delay', None)
        if watch['webdriver_delay'] is not None:
            self.fetcher.render_extract_delay = watch.get('webdriver_delay')
        elif system_webdriver_delay is not None:
            self.fetcher.render_extract_delay = system_webdriver_delay

        if watch.get('webdriver_js_execute_code') is not None and watch.get('webdriver_js_execute_code').strip():
            self.fetcher.webdriver_js_execute_code = watch.get('webdriver_js_execute_code')

        # Requests for PDF's, images etc should be passwd the is_binary flag
        is_binary = watch.is_pdf

        # And here we go! call the right browser with browser-specific settings
        self.fetcher.run(url, timeout, request_headers, request_body, request_method, ignore_status_codes, watch.get('include_filters'),
                    is_binary=is_binary)
        self.fetcher.quit()

        # After init, call run() which will do the actual change-detection

    @abstractmethod
    def run(self, uuid, skip_when_checksum_same=True):
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
