import time
from backend import content_fetcher
import hashlib
from inscriptis import get_text
import urllib3
from . import html_tools

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from selenium import webdriver
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities


# Some common stuff here that can be moved to a base class
class perform_site_check():

    def __init__(self, *args, datastore, **kwargs):
        super().__init__(*args, **kwargs)
        self.datastore = datastore

    def strip_ignore_text(self, content, list_ignore_text):
        import re
        ignore = []
        ignore_regex = []
        for k in list_ignore_text:

            # Is it a regex?
            if k[0] == '/':
                ignore_regex.append(k.strip(" /"))
            else:
                ignore.append(k)

        output = []
        for line in content.splitlines():

            # Always ignore blank lines in this mode. (when this function gets called)
            if len(line.strip()):
                regex_matches = False

                # if any of these match, skip
                for regex in ignore_regex:
                    try:
                        if re.search(regex, line, re.IGNORECASE):
                            regex_matches = True
                    except Exception as e:
                        continue

                if not regex_matches and not any(skip_text in line for skip_text in ignore):
                    output.append(line.encode('utf8'))

        return "\n".encode('utf8').join(output)



    def run(self, uuid):
        timestamp = int(time.time())  # used for storage etc too

        changed_detected = False
        stripped_text_from_html = ""

        update_obj = {'previous_md5': self.datastore.data['watching'][uuid]['previous_md5'],
                      'history': {},
                      "last_checked": timestamp
                      }

        extra_headers = self.datastore.get_val(uuid, 'headers')

        # Tweak the base config with the per-watch ones
        request_headers = self.datastore.data['settings']['headers'].copy()
        request_headers.update(extra_headers)

        # https://github.com/psf/requests/issues/4525
        # Requests doesnt yet support brotli encoding, so don't put 'br' here, be totally sure that the user cannot
        # do this by accident.
        if 'Accept-Encoding' in request_headers and "br" in request_headers['Accept-Encoding']:
            request_headers['Accept-Encoding'] = request_headers['Accept-Encoding'].replace(', br', '')

        # @todo check the failures are really handled how we expect

        else:
            timeout = self.datastore.data['settings']['requests']['timeout']
            url = self.datastore.get_val(uuid, 'url')

            # Pluggable content fetcher
            prefer_backend = self.datastore.data['watching'][uuid]['fetch_backend']
            if hasattr(content_fetcher, prefer_backend):
                klass = getattr(content_fetcher, prefer_backend)
            else:
                # If the klass doesnt exist, just use a default
                klass = getattr(content_fetcher, "html_requests")


            fetcher = klass()
            fetcher.run(url, timeout, request_headers)
            # Fetching complete, now filters
            # @todo move to class / maybe inside of fetcher abstract base?

            is_html = True
            css_filter_rule = self.datastore.data['watching'][uuid]['css_filter']
            if css_filter_rule and len(css_filter_rule.strip()):
                if 'json:' in css_filter_rule:
                    stripped_text_from_html = html_tools.extract_json_as_string(content=fetcher.content, jsonpath_filter=css_filter_rule)
                    is_html = False
                else:
                    # CSS Filter, extract the HTML that matches and feed that into the existing inscriptis::get_text
                    stripped_text_from_html = html_tools.css_filter(css_filter=css_filter_rule, html_content=fetcher.content)

            if is_html:
                # CSS Filter, extract the HTML that matches and feed that into the existing inscriptis::get_text
                html_content = fetcher.content
                css_filter_rule = self.datastore.data['watching'][uuid]['css_filter']
                if css_filter_rule and len(css_filter_rule.strip()):
                    html_content = html_tools.css_filter(css_filter=css_filter_rule, html_content=fetcher.content)

                # get_text() via inscriptis
                stripped_text_from_html = get_text(html_content)

            # We rely on the actual text in the html output.. many sites have random script vars etc,
            # in the future we'll implement other mechanisms.

            update_obj["last_check_status"] = fetcher.get_last_status_code()
            update_obj["last_error"] = False


            # If there's text to skip
            # @todo we could abstract out the get_text() to handle this cleaner
            if len(self.datastore.data['watching'][uuid]['ignore_text']):
                stripped_text_from_html = self.strip_ignore_text(stripped_text_from_html,
                                                 self.datastore.data['watching'][uuid]['ignore_text'])
            else:
                stripped_text_from_html = stripped_text_from_html.encode('utf8')


            fetched_md5 = hashlib.md5(stripped_text_from_html).hexdigest()

            # could be None or False depending on JSON type
            if self.datastore.data['watching'][uuid]['previous_md5'] != fetched_md5:
                changed_detected = True

                # Don't confuse people by updating as last-changed, when it actually just changed from None..
                if self.datastore.get_val(uuid, 'previous_md5'):
                    update_obj["last_changed"] = timestamp

                update_obj["previous_md5"] = fetched_md5

            # Extract title as title
            if is_html and self.datastore.data['settings']['application']['extract_title_as_title']:
                if not self.datastore.data['watching'][uuid]['title'] or not len(self.datastore.data['watching'][uuid]['title']):
                    update_obj['title'] = html_tools.extract_element(find='title', html_content=fetcher.content)


        return changed_detected, update_obj, stripped_text_from_html
