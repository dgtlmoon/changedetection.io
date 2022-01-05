import time
from changedetectionio import content_fetcher
import hashlib
from inscriptis import get_text
import urllib3
from . import html_tools
import re

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


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

        watch = self.datastore.data['watching'][uuid]

        update_obj = {}

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
            request_body = self.datastore.get_val(uuid, 'body')
            request_method = self.datastore.get_val(uuid, 'method')

            # Pluggable content fetcher
            prefer_backend = watch['fetch_backend']
            if hasattr(content_fetcher, prefer_backend):
                klass = getattr(content_fetcher, prefer_backend)
            else:
                # If the klass doesnt exist, just use a default
                klass = getattr(content_fetcher, "html_requests")


            fetcher = klass()
            fetcher.run(url, timeout, request_headers, request_body, request_method)
            # Fetching complete, now filters
            # @todo move to class / maybe inside of fetcher abstract base?

            # @note: I feel like the following should be in a more obvious chain system
            #  - Check filter text
            #  - Is the checksum different?
            #  - Do we convert to JSON?
            # https://stackoverflow.com/questions/41817578/basic-method-chaining ?
            # return content().textfilter().jsonextract().checksumcompare() ?

            is_json = fetcher.headers.get('Content-Type', '') == 'application/json'
            is_html = not is_json
            css_filter_rule = watch['css_filter']

            has_filter_rule = css_filter_rule and len(css_filter_rule.strip())
            if is_json and not has_filter_rule:
                css_filter_rule = "json:$"
                has_filter_rule = True

            if has_filter_rule:
                if 'json:' in css_filter_rule:
                    stripped_text_from_html = html_tools.extract_json_as_string(content=fetcher.content, jsonpath_filter=css_filter_rule)
                    is_html = False

            if is_html:
                # CSS Filter, extract the HTML that matches and feed that into the existing inscriptis::get_text
                html_content = fetcher.content
                if has_filter_rule:
                    # For HTML/XML we offer xpath as an option, just start a regular xPath "/.."
                    if css_filter_rule[0] == '/':
                        html_content = html_tools.xpath_filter(xpath_filter=css_filter_rule, html_content=fetcher.content)
                    else:
                        # CSS Filter, extract the HTML that matches and feed that into the existing inscriptis::get_text
                        html_content = html_tools.css_filter(css_filter=css_filter_rule, html_content=fetcher.content)

                # get_text() via inscriptis
                stripped_text_from_html = get_text(html_content)

            # Re #340 - return the content before the 'ignore text' was applied
            text_content_before_ignored_filter = stripped_text_from_html.encode('utf-8')

            # We rely on the actual text in the html output.. many sites have random script vars etc,
            # in the future we'll implement other mechanisms.

            update_obj["last_check_status"] = fetcher.get_last_status_code()
            update_obj["last_error"] = False

            # If there's text to skip
            # @todo we could abstract out the get_text() to handle this cleaner
            text_to_ignore = watch.get('ignore_text', []) + self.datastore.data['settings']['application'].get('global_ignore_text', [])
            if len(text_to_ignore):
                stripped_text_from_html = self.strip_ignore_text(stripped_text_from_html, text_to_ignore)
            else:
                stripped_text_from_html = stripped_text_from_html.encode('utf8')

            # Re #133 - if we should strip whitespaces from triggering the change detected comparison
            if self.datastore.data['settings']['application'].get('ignore_whitespace', False):
                fetched_md5 = hashlib.md5(stripped_text_from_html.translate(None, b'\r\n\t ')).hexdigest()
            else:
                fetched_md5 = hashlib.md5(stripped_text_from_html).hexdigest()

            # On the first run of a site, watch['previous_md5'] will be an empty string, set it the current one.
            if not len(watch['previous_md5']):
                watch['previous_md5'] = fetched_md5
                update_obj["previous_md5"] = fetched_md5

            blocked_by_not_found_trigger_text = False

            if len(watch['trigger_text']):
                blocked_by_not_found_trigger_text = True
                for line in watch['trigger_text']:
                    # Because JSON wont serialize a re.compile object
                    if line[0] == '/' and line[-1] == '/':
                        regex = re.compile(line.strip('/'), re.IGNORECASE)
                        # Found it? so we don't wait for it anymore
                        r = re.search(regex, str(stripped_text_from_html))
                        if r:
                            blocked_by_not_found_trigger_text = False
                            break

                    elif line.lower() in str(stripped_text_from_html).lower():
                        # We found it don't wait for it.
                        blocked_by_not_found_trigger_text = False
                        break



            if not blocked_by_not_found_trigger_text and watch['previous_md5'] != fetched_md5:
                changed_detected = True
                update_obj["previous_md5"] = fetched_md5
                update_obj["last_changed"] = timestamp


            # Extract title as title
            if is_html:
                if self.datastore.data['settings']['application']['extract_title_as_title'] or watch['extract_title_as_title']:
                    if not watch['title'] or not len(watch['title']):
                        update_obj['title'] = html_tools.extract_element(find='title', html_content=fetcher.content)


        return changed_detected, update_obj, text_content_before_ignored_filter
