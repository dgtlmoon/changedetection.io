# HTML to TEXT/JSON DIFFERENCE self.fetcher

import hashlib
import json
import os
import re
import urllib3

from changedetectionio.processors import difference_detection_processor
from changedetectionio.html_tools import PERL_STYLE_REGEX, cdata_in_document_to_text, TRANSLATE_WHITESPACE_TABLE
from changedetectionio import html_tools, content_fetchers
from changedetectionio.blueprint.price_data_follower import PRICE_DATA_TRACK_ACCEPT, PRICE_DATA_TRACK_REJECT
from loguru import logger

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

name = 'Webpage Text/HTML, JSON and PDF changes'
description = 'Detects all text changes where possible'

json_filter_prefixes = ['json:', 'jq:', 'jqraw:']

class FilterNotFoundInResponse(ValueError):
    def __init__(self, msg, screenshot=None, xpath_data=None):
        self.screenshot = screenshot
        self.xpath_data = xpath_data
        ValueError.__init__(self, msg)


class PDFToHTMLToolNotFound(ValueError):
    def __init__(self, msg):
        ValueError.__init__(self, msg)


# Some common stuff here that can be moved to a base class
# (set_proxy_from_list)
class perform_site_check(difference_detection_processor):

    def run_changedetection(self, watch):
        changed_detected = False
        html_content = ""
        screenshot = False  # as bytes
        stripped_text_from_html = ""

        if not watch:
            raise Exception("Watch no longer exists.")

        # Unset any existing notification error
        update_obj = {'last_notification_error': False, 'last_error': False}

        url = watch.link

        self.screenshot = self.fetcher.screenshot
        self.xpath_data = self.fetcher.xpath_data

        # Track the content type
        update_obj['content_type'] = self.fetcher.get_all_headers().get('content-type', '').lower()

        # Watches added automatically in the queue manager will skip if its the same checksum as the previous run
        # Saves a lot of CPU
        update_obj['previous_md5_before_filters'] = hashlib.md5(self.fetcher.content.encode('utf-8')).hexdigest()

        # Fetching complete, now filters

        # @note: I feel like the following should be in a more obvious chain system
        #  - Check filter text
        #  - Is the checksum different?
        #  - Do we convert to JSON?
        # https://stackoverflow.com/questions/41817578/basic-method-chaining ?
        # return content().textfilter().jsonextract().checksumcompare() ?

        is_json = 'application/json' in self.fetcher.get_all_headers().get('content-type', '').lower()
        is_html = not is_json
        is_rss = False

        ctype_header = self.fetcher.get_all_headers().get('content-type', '').lower()
        # Go into RSS preprocess for converting CDATA/comment to usable text
        if any(substring in ctype_header for substring in ['application/xml', 'application/rss', 'text/xml']):
            if '<rss' in self.fetcher.content[:100].lower():
                self.fetcher.content = cdata_in_document_to_text(html_content=self.fetcher.content)
                is_rss = True

        # source: support, basically treat it as plaintext
        if watch.is_source_type_url:
            is_html = False
            is_json = False

        inline_pdf = self.fetcher.get_all_headers().get('content-disposition', '') and '%PDF-1' in self.fetcher.content[:10]
        if watch.is_pdf or 'application/pdf' in self.fetcher.get_all_headers().get('content-type', '').lower() or inline_pdf:
            from shutil import which
            tool = os.getenv("PDF_TO_HTML_TOOL", "pdftohtml")
            if not which(tool):
                raise PDFToHTMLToolNotFound("Command-line `{}` tool was not found in system PATH, was it installed?".format(tool))

            import subprocess
            proc = subprocess.Popen(
                [tool, '-stdout', '-', '-s', 'out.pdf', '-i'],
                stdout=subprocess.PIPE,
                stdin=subprocess.PIPE)
            proc.stdin.write(self.fetcher.raw_content)
            proc.stdin.close()
            self.fetcher.content = proc.stdout.read().decode('utf-8')
            proc.wait(timeout=60)

            # Add a little metadata so we know if the file changes (like if an image changes, but the text is the same
            # @todo may cause problems with non-UTF8?
            metadata = "<p>Added by changedetection.io: Document checksum - {} Filesize - {} bytes</p>".format(
                hashlib.md5(self.fetcher.raw_content).hexdigest().upper(),
                len(self.fetcher.content))

            self.fetcher.content = self.fetcher.content.replace('</body>', metadata + '</body>')

        # Better would be if Watch.model could access the global data also
        # and then use getattr https://docs.python.org/3/reference/datamodel.html#object.__getitem__
        # https://realpython.com/inherit-python-dict/ instead of doing it procedurely
        include_filters_from_tags = self.datastore.get_tag_overrides_for_watch(uuid=watch.get('uuid'), attr='include_filters')

        # 1845 - remove duplicated filters in both group and watch include filter
        include_filters_rule = list(dict.fromkeys(watch.get('include_filters', []) + include_filters_from_tags))

        subtractive_selectors = [*self.datastore.get_tag_overrides_for_watch(uuid=watch.get('uuid'), attr='subtractive_selectors'),
                                 *watch.get("subtractive_selectors", []),
                                 *self.datastore.data["settings"]["application"].get("global_subtractive_selectors", [])
                                 ]

        # Inject a virtual LD+JSON price tracker rule
        if watch.get('track_ldjson_price_data', '') == PRICE_DATA_TRACK_ACCEPT:
            include_filters_rule += html_tools.LD_JSON_PRODUCT_OFFER_SELECTORS

        has_filter_rule = len(include_filters_rule) and len(include_filters_rule[0].strip())
        has_subtractive_selectors = len(subtractive_selectors) and len(subtractive_selectors[0].strip())

        if is_json and not has_filter_rule:
            include_filters_rule.append("json:$")
            has_filter_rule = True

        if is_json:
            # Sort the JSON so we dont get false alerts when the content is just re-ordered
            try:
                self.fetcher.content = json.dumps(json.loads(self.fetcher.content), sort_keys=True)
            except Exception as e:
                # Might have just been a snippet, or otherwise bad JSON, continue
                pass

        if has_filter_rule:
            for filter in include_filters_rule:
                if any(prefix in filter for prefix in json_filter_prefixes):
                    stripped_text_from_html += html_tools.extract_json_as_string(content=self.fetcher.content, json_filter=filter)
                    is_html = False

        if is_html or watch.is_source_type_url:

            # CSS Filter, extract the HTML that matches and feed that into the existing inscriptis::get_text
            self.fetcher.content = html_tools.workarounds_for_obfuscations(self.fetcher.content)
            html_content = self.fetcher.content

            # If not JSON,  and if it's not text/plain..
            if 'text/plain' in self.fetcher.get_all_headers().get('content-type', '').lower():
                # Don't run get_text or xpath/css filters on plaintext
                stripped_text_from_html = html_content
            else:
                # Does it have some ld+json price data? used for easier monitoring
                update_obj['has_ldjson_price_data'] = html_tools.has_ldjson_product_info(self.fetcher.content)

                # Then we assume HTML
                if has_filter_rule:
                    html_content = ""

                    for filter_rule in include_filters_rule:
                        # For HTML/XML we offer xpath as an option, just start a regular xPath "/.."
                        if filter_rule[0] == '/' or filter_rule.startswith('xpath:'):
                            html_content += html_tools.xpath_filter(xpath_filter=filter_rule.replace('xpath:', ''),
                                                                    html_content=self.fetcher.content,
                                                                    append_pretty_line_formatting=not watch.is_source_type_url,
                                                                    is_rss=is_rss)

                        elif filter_rule.startswith('xpath1:'):
                            html_content += html_tools.xpath1_filter(xpath_filter=filter_rule.replace('xpath1:', ''),
                                                                     html_content=self.fetcher.content,
                                                                     append_pretty_line_formatting=not watch.is_source_type_url,
                                                                     is_rss=is_rss)
                        else:
                            html_content += html_tools.include_filters(include_filters=filter_rule,
                                                                       html_content=self.fetcher.content,
                                                                       append_pretty_line_formatting=not watch.is_source_type_url)

                    if not html_content.strip():
                        raise FilterNotFoundInResponse(msg=include_filters_rule, screenshot=self.fetcher.screenshot, xpath_data=self.fetcher.xpath_data)

                if has_subtractive_selectors:
                    html_content = html_tools.element_removal(subtractive_selectors, html_content)

                if watch.is_source_type_url:
                    stripped_text_from_html = html_content
                else:
                    # extract text
                    do_anchor = self.datastore.data["settings"]["application"].get("render_anchor_tag_content", False)
                    stripped_text_from_html = html_tools.html_to_text(html_content=html_content,
                                                                      render_anchor_tag_content=do_anchor,
                                                                      is_rss=is_rss)  # 1874 activate the <title workaround hack

        if watch.get('trim_text_whitespace'):
            stripped_text_from_html = '\n'.join(line.strip() for line in stripped_text_from_html.replace("\n\n", "\n").splitlines())

        # Re #340 - return the content before the 'ignore text' was applied
        # Also used to calculate/show what was removed
        text_content_before_ignored_filter = stripped_text_from_html

        # @todo whitespace coming from missing rtrim()?
        # stripped_text_from_html could be based on their preferences, replace the processed text with only that which they want to know about.
        # Rewrite's the processing text based on only what diff result they want to see

        if watch.has_special_diff_filter_options_set() and len(watch.history.keys()):
            # Now the content comes from the diff-parser and not the returned HTTP traffic, so could be some differences
            from changedetectionio import diff
            # needs to not include (added) etc or it may get used twice
            # Replace the processed text with the preferred result
            rendered_diff = diff.render_diff(previous_version_file_contents=watch.get_last_fetched_text_before_filters(),
                                             newest_version_file_contents=stripped_text_from_html,
                                             include_equal=False,  # not the same lines
                                             include_added=watch.get('filter_text_added', True),
                                             include_removed=watch.get('filter_text_removed', True),
                                             include_replaced=watch.get('filter_text_replaced', True),
                                             line_feed_sep="\n",
                                             include_change_type_prefix=False)

            watch.save_last_text_fetched_before_filters(text_content_before_ignored_filter.encode('utf-8'))

            if not rendered_diff and stripped_text_from_html:
                # We had some content, but no differences were found
                # Store our new file as the MD5 so it will trigger in the future
                c = hashlib.md5(stripped_text_from_html.translate(TRANSLATE_WHITESPACE_TABLE).encode('utf-8')).hexdigest()
                return False, {'previous_md5': c}, stripped_text_from_html.encode('utf-8')
            else:
                stripped_text_from_html = rendered_diff

        # Treat pages with no renderable text content as a change? No by default
        empty_pages_are_a_change = self.datastore.data['settings']['application'].get('empty_pages_are_a_change', False)
        if not is_json and not empty_pages_are_a_change and len(stripped_text_from_html.strip()) == 0:
            raise content_fetchers.exceptions.ReplyWithContentButNoText(url=url,
                                                            status_code=self.fetcher.get_last_status_code(),
                                                            screenshot=self.fetcher.screenshot,
                                                            has_filters=has_filter_rule,
                                                            html_content=html_content,
                                                            xpath_data=self.fetcher.xpath_data
                                                            )

        # We rely on the actual text in the html output.. many sites have random script vars etc,
        # in the future we'll implement other mechanisms.

        update_obj["last_check_status"] = self.fetcher.get_last_status_code()

        # 615 Extract text by regex
        extract_text = watch.get('extract_text', [])
        if len(extract_text) > 0:
            regex_matched_output = []
            for s_re in extract_text:
                # incase they specified something in '/.../x'
                if re.search(PERL_STYLE_REGEX, s_re, re.IGNORECASE):
                    regex = html_tools.perl_style_slash_enclosed_regex_to_options(s_re)
                    result = re.findall(regex, stripped_text_from_html)

                    for l in result:
                        if type(l) is tuple:
                            # @todo - some formatter option default (between groups)
                            regex_matched_output += list(l) + ['\n']
                        else:
                            # @todo - some formatter option default (between each ungrouped result)
                            regex_matched_output += [l] + ['\n']
                else:
                    # Doesnt look like regex, just hunt for plaintext and return that which matches
                    # `stripped_text_from_html` will be bytes, so we must encode s_re also to bytes
                    r = re.compile(re.escape(s_re), re.IGNORECASE)
                    res = r.findall(stripped_text_from_html)
                    if res:
                        for match in res:
                            regex_matched_output += [match] + ['\n']

            ##########################################################
            stripped_text_from_html = ''

            if regex_matched_output:
                # @todo some formatter for presentation?
                stripped_text_from_html = ''.join(regex_matched_output)

        if watch.get('remove_duplicate_lines'):
            stripped_text_from_html = '\n'.join(dict.fromkeys(line for line in stripped_text_from_html.replace("\n\n", "\n").splitlines()))


        if watch.get('sort_text_alphabetically'):
            # Note: Because a <p>something</p> will add an extra line feed to signify the paragraph gap
            # we end up with 'Some text\n\n', sorting will add all those extra \n at the start, so we remove them here.
            stripped_text_from_html = stripped_text_from_html.replace("\n\n", "\n")
            stripped_text_from_html = '\n'.join(sorted(stripped_text_from_html.splitlines(), key=lambda x: x.lower()))

### CALCULATE MD5
        # If there's text to ignore
        text_to_ignore = watch.get('ignore_text', []) + self.datastore.data['settings']['application'].get('global_ignore_text', [])
        text_for_checksuming = stripped_text_from_html
        if text_to_ignore:
            text_for_checksuming = html_tools.strip_ignore_text(stripped_text_from_html, text_to_ignore)

        # Re #133 - if we should strip whitespaces from triggering the change detected comparison
        if text_for_checksuming and self.datastore.data['settings']['application'].get('ignore_whitespace', False):
            fetched_md5 = hashlib.md5(text_for_checksuming.translate(TRANSLATE_WHITESPACE_TABLE).encode('utf-8')).hexdigest()
        else:
            fetched_md5 = hashlib.md5(text_for_checksuming.encode('utf-8')).hexdigest()

        ############ Blocking rules, after checksum #################
        blocked = False

        trigger_text = watch.get('trigger_text', [])
        if len(trigger_text):
            # Assume blocked
            blocked = True
            # Filter and trigger works the same, so reuse it
            # It should return the line numbers that match
            # Unblock flow if the trigger was found (some text remained after stripped what didnt match)
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


        # Looks like something changed, but did it match all the rules?
        if blocked:
            changed_detected = False
        else:
            # The main thing that all this at the moment comes down to :)
            if watch.get('previous_md5') != fetched_md5:
                changed_detected = True

            # Always record the new checksum
            update_obj["previous_md5"] = fetched_md5

            # On the first run of a site, watch['previous_md5'] will be None, set it the current one.
            if not watch.get('previous_md5'):
                watch['previous_md5'] = fetched_md5

        logger.debug(f"Watch UUID {watch.get('uuid')} content check - Previous MD5: {watch.get('previous_md5')}, Fetched MD5 {fetched_md5}")

        if changed_detected:
            if watch.get('check_unique_lines', False):
                ignore_whitespace = self.datastore.data['settings']['application'].get('ignore_whitespace')

                has_unique_lines = watch.lines_contain_something_unique_compared_to_history(
                    lines=stripped_text_from_html.splitlines(),
                    ignore_whitespace=ignore_whitespace
                )

                # One or more lines? unsure?
                if not has_unique_lines:
                    logger.debug(f"check_unique_lines: UUID {watch.get('uuid')} didnt have anything new setting change_detected=False")
                    changed_detected = False
                else:
                    logger.debug(f"check_unique_lines: UUID {watch.get('uuid')} had unique content")


        # stripped_text_from_html - Everything after filters and NO 'ignored' content
        return changed_detected, update_obj, stripped_text_from_html
