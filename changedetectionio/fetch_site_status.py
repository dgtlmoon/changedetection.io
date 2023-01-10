import hashlib
import json
import logging
import os
import re
import urllib3

from changedetectionio import content_fetcher, html_tools
from changedetectionio.blueprint.price_data_follower import PRICE_DATA_TRACK_ACCEPT, PRICE_DATA_TRACK_REJECT
from copy import deepcopy

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class FilterNotFoundInResponse(ValueError):
    def __init__(self, msg):
        ValueError.__init__(self, msg)

class PDFToHTMLToolNotFound(ValueError):
    def __init__(self, msg):
        ValueError.__init__(self, msg)


# Some common stuff here that can be moved to a base class
# (set_proxy_from_list)
class perform_site_check():
    screenshot = None
    xpath_data = None

    def __init__(self, *args, datastore, **kwargs):
        super().__init__(*args, **kwargs)
        self.datastore = datastore

    # Doesn't look like python supports forward slash auto enclosure in re.findall
    # So convert it to inline flag "foobar(?i)" type configuration
    def forward_slash_enclosed_regex_to_options(self, regex):
        res = re.search(r'^/(.*?)/(\w+)$', regex, re.IGNORECASE)

        if res:
            regex = res.group(1)
            regex += '(?{})'.format(res.group(2))
        else:
            regex += '(?{})'.format('i')

        return regex

    def run(self, uuid, skip_when_checksum_same=True):
        changed_detected = False
        screenshot = False  # as bytes
        stripped_text_from_html = ""

        # DeepCopy so we can be sure we don't accidently change anything by reference
        watch = deepcopy(self.datastore.data['watching'].get(uuid))

        if not watch:
            return

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

        # source: support
        is_source = False
        if url.startswith('source:'):
            url = url.replace('source:', '')
            is_source = True

        # Pluggable content fetcher
        prefer_backend = watch.get_fetch_backend
        if hasattr(content_fetcher, prefer_backend):
            klass = getattr(content_fetcher, prefer_backend)
        else:
            # If the klass doesnt exist, just use a default
            klass = getattr(content_fetcher, "html_requests")

        proxy_id = self.datastore.get_preferred_proxy_for_watch(uuid=uuid)
        proxy_url = None
        if proxy_id:
            proxy_url = self.datastore.proxy_list.get(proxy_id).get('url')
            print("UUID {} Using proxy {}".format(uuid, proxy_url))

        fetcher = klass(proxy_override=proxy_url)

        # Configurable per-watch or global extra delay before extracting text (for webDriver types)
        system_webdriver_delay = self.datastore.data['settings']['application'].get('webdriver_delay', None)
        if watch['webdriver_delay'] is not None:
            fetcher.render_extract_delay = watch.get('webdriver_delay')
        elif system_webdriver_delay is not None:
            fetcher.render_extract_delay = system_webdriver_delay

        # Possible conflict
        if prefer_backend == 'html_webdriver':
            fetcher.browser_steps = watch.get('browser_steps', None)
            fetcher.browser_steps_screenshot_path = os.path.join(self.datastore.datastore_path, uuid)

        if watch.get('webdriver_js_execute_code') is not None and watch.get('webdriver_js_execute_code').strip():
            fetcher.webdriver_js_execute_code = watch.get('webdriver_js_execute_code')

        # requests for PDF's, images etc should be passwd the is_binary flag
        is_binary = watch.is_pdf

        fetcher.run(url, timeout, request_headers, request_body, request_method, ignore_status_codes, watch.get('include_filters'), is_binary=is_binary)
        fetcher.quit()

        self.screenshot = fetcher.screenshot
        self.xpath_data = fetcher.xpath_data

        # Track the content type
        update_obj['content_type'] = fetcher.headers.get('Content-Type', '')

        # Watches added automatically in the queue manager will skip if its the same checksum as the previous run
        # Saves a lot of CPU
        update_obj['previous_md5_before_filters'] = hashlib.md5(fetcher.content.encode('utf-8')).hexdigest()
        if skip_when_checksum_same:
            if update_obj['previous_md5_before_filters'] == watch.get('previous_md5_before_filters'):
                raise content_fetcher.checksumFromPreviousCheckWasTheSame()


        # Fetching complete, now filters
        # @todo move to class / maybe inside of fetcher abstract base?

        # @note: I feel like the following should be in a more obvious chain system
        #  - Check filter text
        #  - Is the checksum different?
        #  - Do we convert to JSON?
        # https://stackoverflow.com/questions/41817578/basic-method-chaining ?
        # return content().textfilter().jsonextract().checksumcompare() ?

        is_json = 'application/json' in fetcher.headers.get('Content-Type', '')
        is_html = not is_json

        # source: support, basically treat it as plaintext
        if is_source:
            is_html = False
            is_json = False

        if watch.is_pdf or 'application/pdf' in fetcher.headers.get('Content-Type', '').lower():
            from shutil import which
            tool = os.getenv("PDF_TO_HTML_TOOL", "pdftohtml")
            if not which(tool):
                raise PDFToHTMLToolNotFound("Command-line `{}` tool was not found in system PATH, was it installed?".format(tool))

            import subprocess
            proc = subprocess.Popen(
                [tool, '-stdout', '-', '-s', 'out.pdf', '-i'],
                stdout=subprocess.PIPE,
                stdin=subprocess.PIPE)
            proc.stdin.write(fetcher.raw_content)
            proc.stdin.close()
            fetcher.content = proc.stdout.read().decode('utf-8')
            proc.wait(timeout=60)

            # Add a little metadata so we know if the file changes (like if an image changes, but the text is the same
            # @todo may cause problems with non-UTF8?
            metadata = "<p>Added by changedetection.io: Document checksum - {} Filesize - {} bytes</p>".format(
                hashlib.md5(fetcher.raw_content).hexdigest().upper(),
                len(fetcher.content))

            fetcher.content = fetcher.content.replace('</body>', metadata + '</body>')


        include_filters_rule = deepcopy(watch.get('include_filters', []))
        # include_filters_rule = watch['include_filters']
        subtractive_selectors = watch.get(
            "subtractive_selectors", []
        ) + self.datastore.data["settings"]["application"].get(
            "global_subtractive_selectors", []
        )

        # Inject a virtual LD+JSON price tracker rule
        if watch.get('track_ldjson_price_data', '') == PRICE_DATA_TRACK_ACCEPT:
            include_filters_rule.append(html_tools.LD_JSON_PRODUCT_OFFER_SELECTOR)

        has_filter_rule = include_filters_rule and len("".join(include_filters_rule).strip())
        has_subtractive_selectors = subtractive_selectors and len(subtractive_selectors[0].strip())

        if is_json and not has_filter_rule:
            include_filters_rule.append("json:$")
            has_filter_rule = True

        if is_json:
            # Sort the JSON so we dont get false alerts when the content is just re-ordered
            try:
                fetcher.content = json.dumps(json.loads(fetcher.content), sort_keys=True)
            except Exception as e:
                # Might have just been a snippet, or otherwise bad JSON, continue
                pass

        if has_filter_rule:
            json_filter_prefixes = ['json:', 'jq:']
            for filter in include_filters_rule:
                if any(prefix in filter for prefix in json_filter_prefixes):
                    stripped_text_from_html += html_tools.extract_json_as_string(content=fetcher.content, json_filter=filter)
                    is_html = False



        if is_html or is_source:

            # CSS Filter, extract the HTML that matches and feed that into the existing inscriptis::get_text
            fetcher.content = html_tools.workarounds_for_obfuscations(fetcher.content)
            html_content = fetcher.content

            # If not JSON,  and if it's not text/plain..
            if 'text/plain' in fetcher.headers.get('Content-Type', '').lower():
                # Don't run get_text or xpath/css filters on plaintext
                stripped_text_from_html = html_content
            else:
                # Does it have some ld+json price data? used for easier monitoring
                update_obj['has_ldjson_price_data'] = html_tools.has_ldjson_product_info(fetcher.content)

                # Then we assume HTML
                if has_filter_rule:
                    html_content = ""

                    for filter_rule in include_filters_rule:
                        # For HTML/XML we offer xpath as an option, just start a regular xPath "/.."
                        if filter_rule[0] == '/' or filter_rule.startswith('xpath:'):
                            html_content += html_tools.xpath_filter(xpath_filter=filter_rule.replace('xpath:', ''),
                                                                    html_content=fetcher.content,
                                                                    append_pretty_line_formatting=not is_source)
                        else:
                            # CSS Filter, extract the HTML that matches and feed that into the existing inscriptis::get_text
                            html_content += html_tools.include_filters(include_filters=filter_rule,
                                                                       html_content=fetcher.content,
                                                                       append_pretty_line_formatting=not is_source)

                    if not html_content.strip():
                        raise FilterNotFoundInResponse(include_filters_rule)

                if has_subtractive_selectors:
                    html_content = html_tools.element_removal(subtractive_selectors, html_content)

                if is_source:
                    stripped_text_from_html = html_content
                else:
                    # extract text
                    do_anchor = self.datastore.data["settings"]["application"].get("render_anchor_tag_content", False)
                    stripped_text_from_html = \
                        html_tools.html_to_text(
                            html_content,
                            render_anchor_tag_content=do_anchor
                        )

        # Re #340 - return the content before the 'ignore text' was applied
        text_content_before_ignored_filter = stripped_text_from_html.encode('utf-8')

        # Treat pages with no renderable text content as a change? No by default
        empty_pages_are_a_change = self.datastore.data['settings']['application'].get('empty_pages_are_a_change', False)
        if not is_json and not empty_pages_are_a_change and len(stripped_text_from_html.strip()) == 0:
            raise content_fetcher.ReplyWithContentButNoText(url=url, status_code=fetcher.get_last_status_code(), screenshot=screenshot)

        # We rely on the actual text in the html output.. many sites have random script vars etc,
        # in the future we'll implement other mechanisms.

        update_obj["last_check_status"] = fetcher.get_last_status_code()

        # If there's text to skip
        # @todo we could abstract out the get_text() to handle this cleaner
        text_to_ignore = watch.get('ignore_text', []) + self.datastore.data['settings']['application'].get('global_ignore_text', [])
        if len(text_to_ignore):
            stripped_text_from_html = html_tools.strip_ignore_text(stripped_text_from_html, text_to_ignore)
        else:
            stripped_text_from_html = stripped_text_from_html.encode('utf8')

        # 615 Extract text by regex
        extract_text = watch.get('extract_text', [])
        if len(extract_text) > 0:
            regex_matched_output = []
            for s_re in extract_text:
                # incase they specified something in '/.../x'
                regex = self.forward_slash_enclosed_regex_to_options(s_re)
                result = re.findall(regex.encode('utf-8'), stripped_text_from_html)

                for l in result:
                    if type(l) is tuple:
                        # @todo - some formatter option default (between groups)
                        regex_matched_output += list(l) + [b'\n']
                    else:
                        # @todo - some formatter option default (between each ungrouped result)
                        regex_matched_output += [l] + [b'\n']

            # Now we will only show what the regex matched
            stripped_text_from_html = b''
            text_content_before_ignored_filter = b''
            if regex_matched_output:
                # @todo some formatter for presentation?
                stripped_text_from_html = b''.join(regex_matched_output)
                text_content_before_ignored_filter = stripped_text_from_html

        # Re #133 - if we should strip whitespaces from triggering the change detected comparison
        if self.datastore.data['settings']['application'].get('ignore_whitespace', False):
            fetched_md5 = hashlib.md5(stripped_text_from_html.translate(None, b'\r\n\t ')).hexdigest()
        else:
            fetched_md5 = hashlib.md5(stripped_text_from_html).hexdigest()

        ############ Blocking rules, after checksum #################
        blocked = False

        trigger_text = watch.get('trigger_text', [])
        if len(trigger_text):
            # Assume blocked
            blocked = True
            # Filter and trigger works the same, so reuse it
            # It should return the line numbers that match
            result = html_tools.strip_ignore_text(content=str(stripped_text_from_html),
                                                  wordlist=trigger_text,
                                                  mode="line numbers")
            # Unblock if the trigger was found
            if result:
                blocked = False

        text_should_not_be_present = watch.get('text_should_not_be_present', [])
        if len(text_should_not_be_present):
            # If anything matched, then we should block a change from happening
            result = html_tools.strip_ignore_text(content=str(stripped_text_from_html),
                                                  wordlist=text_should_not_be_present,
                                                  mode="line numbers")
            if result:
                blocked = True

        # The main thing that all this at the moment comes down to :)
        if watch.get('previous_md5') != fetched_md5:
            changed_detected = True

        # Looks like something changed, but did it match all the rules?
        if blocked:
            changed_detected = False

        # Extract title as title
        if is_html:
            if self.datastore.data['settings']['application'].get('extract_title_as_title') or watch['extract_title_as_title']:
                if not watch['title'] or not len(watch['title']):
                    update_obj['title'] = html_tools.extract_element(find='title', html_content=fetcher.content)

        if changed_detected:
            if watch.get('check_unique_lines', False):
                has_unique_lines = watch.lines_contain_something_unique_compared_to_history(lines=stripped_text_from_html.splitlines())
                # One or more lines? unsure?
                if not has_unique_lines:
                    logging.debug("check_unique_lines: UUID {} didnt have anything new setting change_detected=False".format(uuid))
                    changed_detected = False
                else:
                    logging.debug("check_unique_lines: UUID {} had unique content".format(uuid))

        # Always record the new checksum
        update_obj["previous_md5"] = fetched_md5

        # On the first run of a site, watch['previous_md5'] will be None, set it the current one.
        if not watch.get('previous_md5'):
            watch['previous_md5'] = fetched_md5

        return changed_detected, update_obj, text_content_before_ignored_filter
