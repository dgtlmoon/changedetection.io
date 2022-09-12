import hashlib
import imagehash
from PIL import Image
import io
import logging
import os
import re
import time
import urllib3

# fetch processor for requesting and comparing a single image
# can use both requests and playwright/selenium

# - imagehash for change detection (or https://github.com/dgtlmoon/changedetection.io/pull/419/files#diff-7d3854710a6c0faead783f75850100a4c4b69409309200d3a83692dc9783bf6eR17 ?)
# - skimage.metrics import structural_similarity for viewing the diff


from changedetectionio import content_fetcher, html_tools

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from . import fetch_processor


# Some common stuff here that can be moved to a base class
# (set_proxy_from_list)
class perform_site_check(fetch_processor):
    xpath_data = None

    def run(self, uuid):
        changed_detected = False
        screenshot = False  # as bytes
        stripped_text_from_html = ""

        watch = self.datastore.data['watching'].get(uuid)

        # Protect against file:// access
        if re.search(r'^file', watch['url'], re.IGNORECASE) and not os.getenv('ALLOW_FILE_URI', False):
            raise Exception(
                "file:// type access is denied for security reasons."
            )

        # Unset any existing notification error
        update_obj = {'last_notification_error': False, 'last_error': False}

        extra_headers = self.datastore.data['watching'][uuid].get('headers')

        # Tweak the base config with the per-watch ones
        request_headers = self.datastore.data['settings']['headers'].copy()
        request_headers.update(extra_headers)

        # https://github.com/psf/requests/issues/4525
        # Requests doesnt yet support brotli encoding, so don't put 'br' here, be totally sure that the user cannot
        # do this by accident.
        if 'Accept-Encoding' in request_headers and "br" in request_headers['Accept-Encoding']:
            request_headers['Accept-Encoding'] = request_headers['Accept-Encoding'].replace(', br', '')

        timeout = self.datastore.data['settings']['requests']['timeout']
        url = watch.get('url')
        request_body = self.datastore.data['watching'][uuid].get('body')
        request_method = self.datastore.data['watching'][uuid].get('method')
        ignore_status_codes = self.datastore.data['watching'][uuid].get('ignore_status_codes', False)

        prefer_backend = watch['fetch_backend']
        if hasattr(content_fetcher, prefer_backend):
            klass = getattr(content_fetcher, prefer_backend)
        else:
            # If the klass doesnt exist, just use a default
            klass = getattr(content_fetcher, "html_requests")

        proxy_args = self.set_proxy_from_list(watch)
        fetcher = klass(proxy_override=proxy_args)

        fetcher.run(url, timeout, request_headers, request_body, request_method, ignore_status_codes)
        fetcher.quit()

        # if not image/foobar in mimetype
        # raise content_fecther.NotAnImage(mimetype) ?
        # or better to try load with PIL and catch exception?

        update_obj["last_check_status"] = fetcher.get_last_status_code()

        image = Image.open(io.BytesIO(fetcher.raw_content))

        # @todo different choice?
        # https://github.com/JohannesBuchner/imagehash#references
        fetched_hash = str(imagehash.average_hash(image))

        # The main thing that all this at the moment comes down to :)
        if watch['previous_md5'] != fetched_hash:
            changed_detected = True

        # Always record the new checksum
        update_obj["previous_md5"] = fetched_hash

        # On the first run of a site, watch['previous_md5'] will be None, set it the current one.
        if not watch.get('previous_md5'):
            watch['previous_md5'] = fetched_hash

        #self.contents = fetcher.screenshot

        return changed_detected, update_obj
