# HTML to TEXT/JSON DIFFERENCE self.fetcher

import hashlib
import json
import os
import re
import urllib3

from changedetectionio.conditions import execute_ruleset_against_all_plugins
from ..base import difference_detection_processor
from changedetectionio.html_tools import PERL_STYLE_REGEX, cdata_in_document_to_text, TRANSLATE_WHITESPACE_TABLE
from changedetectionio import html_tools, content_fetchers
from changedetectionio.blueprint.price_data_follower import PRICE_DATA_TRACK_ACCEPT
from loguru import logger

from changedetectionio.processors.magic import guess_stream_type

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Translation marker for extraction - allows pybabel to find these strings
def _(x): return x
name = _('Webpage Text/HTML, JSON and PDF changes')
description = _('Detects all text changes where possible')
del _  # Remove marker
processor_weight = -100
list_badge_text = "Text"

JSON_FILTER_PREFIXES = ['json:', 'jq:', 'jqraw:']

# Assume it's this type if the server says nothing on content-type
DEFAULT_WHEN_NO_CONTENT_TYPE_HEADER = 'text/html'

class FilterNotFoundInResponse(ValueError):
    def __init__(self, msg, screenshot=None, xpath_data=None):
        self.screenshot = screenshot
        self.xpath_data = xpath_data
        ValueError.__init__(self, msg)


class PDFToHTMLToolNotFound(ValueError):
    def __init__(self, msg):
        ValueError.__init__(self, msg)


class FilterConfig:
    """Consolidates all filter and rule configurations from watch, tags, and global settings."""

    def __init__(self, watch, datastore):
        self.watch = watch
        self.datastore = datastore
        self.watch_uuid = watch.get('uuid')
        # Cache computed properties to avoid repeated list operations
        self._include_filters_cache = None
        self._subtractive_selectors_cache = None

    def _get_merged_rules(self, attr, include_global=False):
        """Merge rules from watch, tags, and optionally global settings."""
        watch_rules = self.watch.get(attr, [])
        tag_rules = self.datastore.get_tag_overrides_for_watch(uuid=self.watch_uuid, attr=attr)
        rules = list(dict.fromkeys(watch_rules + tag_rules))

        if include_global:
            global_rules = self.datastore.data['settings']['application'].get(f'global_{attr}', [])
            rules = list(dict.fromkeys(rules + global_rules))

        return rules

    @property
    def include_filters(self):
        if self._include_filters_cache is None:
            filters = self._get_merged_rules('include_filters')
            # Inject LD+JSON price tracker rule if enabled
            if self.watch.get('track_ldjson_price_data', '') == PRICE_DATA_TRACK_ACCEPT:
                filters += html_tools.LD_JSON_PRODUCT_OFFER_SELECTORS
            self._include_filters_cache = filters
        return self._include_filters_cache

    @property
    def subtractive_selectors(self):
        if self._subtractive_selectors_cache is None:
            watch_selectors = self.watch.get("subtractive_selectors", [])
            tag_selectors = self.datastore.get_tag_overrides_for_watch(uuid=self.watch_uuid, attr='subtractive_selectors')
            global_selectors = self.datastore.data["settings"]["application"].get("global_subtractive_selectors", [])
            self._subtractive_selectors_cache = [*tag_selectors, *watch_selectors, *global_selectors]
        return self._subtractive_selectors_cache

    @property
    def extract_text(self):
        return self._get_merged_rules('extract_text')

    @property
    def ignore_text(self):
        return self._get_merged_rules('ignore_text', include_global=True)

    @property
    def trigger_text(self):
        return self._get_merged_rules('trigger_text')

    @property
    def text_should_not_be_present(self):
        return self._get_merged_rules('text_should_not_be_present')

    @property
    def block_words(self):
        """Words that block notifications while present (restock alerts)."""
        return self._get_merged_rules('block_words')

    @property
    def trigger_words(self):
        """Words that must appear before notifications are sent."""
        return self._get_merged_rules('trigger_words')

    @property
    def has_include_filters(self):
        return bool(self.include_filters) and bool(self.include_filters[0].strip())

    @property
    def has_include_json_filters(self):
        return any(f.strip().startswith(prefix) for f in self.include_filters for prefix in JSON_FILTER_PREFIXES)

    @property
    def has_subtractive_selectors(self):
        return bool(self.subtractive_selectors) and bool(self.subtractive_selectors[0].strip())


class ContentTransformer:
    """Handles text transformations like trimming, sorting, and deduplication."""

    @staticmethod
    def trim_whitespace(text):
        """Remove leading/trailing whitespace from each line."""
        # Use generator expression to avoid building intermediate list
        return '\n'.join(line.strip() for line in text.replace("\n\n", "\n").splitlines())

    @staticmethod
    def remove_duplicate_lines(text):
        """Remove duplicate lines while preserving order."""
        return '\n'.join(dict.fromkeys(line for line in text.replace("\n\n", "\n").splitlines()))

    @staticmethod
    def sort_alphabetically(text):
        """Sort lines alphabetically (case-insensitive)."""
        # Remove double line feeds before sorting
        text = text.replace("\n\n", "\n")
        return '\n'.join(sorted(text.splitlines(), key=lambda x: x.lower()))

    @staticmethod
    def extract_by_regex(text, regex_patterns):
        """Extract text matching regex patterns."""
        # Use list of strings instead of concatenating lists repeatedly (avoids O(n²) behavior)
        regex_matched_output = []

        for s_re in regex_patterns:
            # Check if it's perl-style regex /.../
            if re.search(PERL_STYLE_REGEX, s_re, re.IGNORECASE):
                regex = html_tools.perl_style_slash_enclosed_regex_to_options(s_re)
                result = re.findall(regex, text)

                for match in result:
                    if type(match) is tuple:
                        regex_matched_output.extend(match)
                        regex_matched_output.append('\n')
                    else:
                        regex_matched_output.append(match)
                        regex_matched_output.append('\n')
            else:
                # Plain text search (case-insensitive)
                r = re.compile(re.escape(s_re), re.IGNORECASE)
                res = r.findall(text)
                if res:
                    for match in res:
                        regex_matched_output.append(match)
                        regex_matched_output.append('\n')

        return ''.join(regex_matched_output) if regex_matched_output else ''


class RuleEngine:
    """Evaluates blocking rules (triggers, conditions, text_should_not_be_present)."""

    @staticmethod
    def evaluate_trigger_text(content, trigger_patterns):
        """
        Check if trigger text is present. If trigger_text is configured,
        content is blocked UNLESS the trigger is found.
        Returns True if blocked, False if allowed.
        """
        if not trigger_patterns:
            return False

        # Assume blocked if trigger_text is configured
        result = html_tools.strip_ignore_text(
            content=str(content),
            wordlist=trigger_patterns,
            mode="line numbers"
        )
        # Unblock if trigger was found
        return not bool(result)

    @staticmethod
    def evaluate_text_should_not_be_present(content, patterns):
        """
        Check if forbidden text is present. If found, block the change.
        Returns True if blocked, False if allowed.
        """
        if not patterns:
            return False

        result = html_tools.strip_ignore_text(
            content=str(content),
            wordlist=patterns,
            mode="line numbers"
        )
        # Block if forbidden text was found
        return bool(result)

    @staticmethod
    def evaluate_block_words(content, patterns):
        """
        Check if block_words are present. If found, block the change.

        Semantics: "Notify when these words DISAPPEAR"
        - Block while words ARE present on page
        - Allow (unblock) when words are NOT present

        Returns True if blocked, False if allowed.
        """
        if not patterns:
            return False

        result = html_tools.strip_ignore_text(
            content=str(content),
            wordlist=patterns,
            mode="line numbers"
        )
        # Block if words ARE found (waiting for them to disappear)
        return bool(result)

    @staticmethod
    def evaluate_trigger_words(content, patterns):
        """
        Check if trigger_words are present. If NOT found, block the change.

        Semantics: "Notify when these words APPEAR"
        - Block while words are NOT present on page
        - Allow (unblock) when words ARE present

        Returns True if blocked, False if allowed.
        """
        if not patterns:
            return False

        result = html_tools.strip_ignore_text(
            content=str(content),
            wordlist=patterns,
            mode="line numbers"
        )
        # Block if words NOT found (waiting for them to appear)
        return not bool(result)

    @staticmethod
    def evaluate_conditions(watch, datastore, content):
        """
        Evaluate custom conditions ruleset.
        Returns True if blocked, False if allowed.
        """
        if not watch.get('conditions') or not watch.get('conditions_match_logic'):
            return False

        conditions_result = execute_ruleset_against_all_plugins(
            current_watch_uuid=watch.get('uuid'),
            application_datastruct=datastore.data,
            ephemeral_data={'text': content}
        )

        # Block if conditions not met
        return not conditions_result.get('result')


class ContentProcessor:
    """Handles content preprocessing, filtering, and extraction."""

    def __init__(self, fetcher, watch, filter_config, datastore):
        self.fetcher = fetcher
        self.watch = watch
        self.filter_config = filter_config
        self.datastore = datastore

    def preprocess_rss(self, content):
        """
        Convert CDATA/comments in RSS to usable text.

        Supports two RSS processing modes:
        - 'default': Inline CDATA replacement (original behavior)
        - 'formatted': Format RSS items with title, link, guid, pubDate, and description (CDATA unmarked)
        """
        from changedetectionio import rss_tools
        rss_mode = self.datastore.data["settings"]["application"].get("rss_reader_mode")
        if rss_mode:
            # Format RSS items nicely with CDATA content unmarked and converted to text
            return rss_tools.format_rss_items(content)
        else:
            # Default: Original inline CDATA replacement
            return cdata_in_document_to_text(html_content=content)

    def preprocess_pdf(self, raw_content):
        """Convert PDF to HTML using external tool."""
        from shutil import which
        tool = os.getenv("PDF_TO_HTML_TOOL", "pdftohtml")
        if not which(tool):
            raise PDFToHTMLToolNotFound(
                f"Command-line `{tool}` tool was not found in system PATH, was it installed?"
            )

        import subprocess
        proc = subprocess.Popen(
            [tool, '-stdout', '-', '-s', 'out.pdf', '-i'],
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE
        )
        proc.stdin.write(raw_content)
        proc.stdin.close()
        html_content = proc.stdout.read().decode('utf-8')
        proc.wait(timeout=60)

        # Add metadata for change detection
        metadata = (
            f"<p>Added by changedetection.io: Document checksum - "
            f"{hashlib.md5(raw_content).hexdigest().upper()} "
            f"Original file size - {len(raw_content)} bytes</p>"
        )
        return html_content.replace('</body>', metadata + '</body>')

    def preprocess_json(self, raw_content):
        """Format and sort JSON content."""
        # Then we re-format it, else it does have filters (later on) which will reformat it anyway
        content = html_tools.extract_json_as_string(content=raw_content, json_filter="json:$")

        # Sort JSON to avoid false alerts from reordering
        try:
            content = json.dumps(json.loads(content), sort_keys=True, indent=2, ensure_ascii=False)
        except Exception:
            # Might be malformed JSON, continue anyway
            pass

        return content

    def apply_include_filters(self, content, stream_content_type):
        """Apply CSS, XPath, or JSON filters to extract specific content."""
        filtered_content = ""

        for filter_rule in self.filter_config.include_filters:
            # XPath filters
            if filter_rule[0] == '/' or filter_rule.startswith('xpath:'):
                filtered_content += html_tools.xpath_filter(
                    xpath_filter=filter_rule.replace('xpath:', ''),
                    html_content=content,
                    append_pretty_line_formatting=not self.watch.is_source_type_url,
                    is_xml=stream_content_type.is_rss or stream_content_type.is_xml
                )

            # XPath1 filters (first match only)
            elif filter_rule.startswith('xpath1:'):
                filtered_content += html_tools.xpath1_filter(
                    xpath_filter=filter_rule.replace('xpath1:', ''),
                    html_content=content,
                    append_pretty_line_formatting=not self.watch.is_source_type_url,
                    is_xml=stream_content_type.is_rss or stream_content_type.is_xml
                )

            # JSON filters
            elif any(filter_rule.startswith(prefix) for prefix in JSON_FILTER_PREFIXES):
                filtered_content += html_tools.extract_json_as_string(
                    content=content,
                    json_filter=filter_rule
                )

            # CSS selectors, default fallback
            else:
                filtered_content += html_tools.include_filters(
                    include_filters=filter_rule,
                    html_content=content,
                    append_pretty_line_formatting=not self.watch.is_source_type_url
                )

        # Raise error if filter returned nothing
        if not filtered_content.strip():
            raise FilterNotFoundInResponse(
                msg=self.filter_config.include_filters,
                screenshot=self.fetcher.screenshot,
                xpath_data=self.fetcher.xpath_data
            )

        return filtered_content

    def apply_subtractive_selectors(self, content):
        """Remove elements matching subtractive selectors."""
        return html_tools.element_removal(self.filter_config.subtractive_selectors, content)

    def extract_text_from_html(self, html_content, stream_content_type):
        """Convert HTML to plain text."""
        do_anchor = self.datastore.data["settings"]["application"].get("render_anchor_tag_content", False)
        return html_tools.html_to_text(
            html_content=html_content,
            render_anchor_tag_content=do_anchor,
            is_rss=stream_content_type.is_rss
        )


class ChecksumCalculator:
    """Calculates checksums with various options."""

    @staticmethod
    def calculate(text, ignore_whitespace=False):
        """Calculate MD5 checksum of text content."""
        if ignore_whitespace:
            text = text.translate(TRANSLATE_WHITESPACE_TABLE)
        return hashlib.md5(text.encode('utf-8')).hexdigest()


# Some common stuff here that can be moved to a base class
# (set_proxy_from_list)
class perform_site_check(difference_detection_processor):

    def run_changedetection(self, watch):
        changed_detected = False

        if not watch:
            raise Exception("Watch no longer exists.")

        # Initialize components
        filter_config = FilterConfig(watch, self.datastore)
        content_processor = ContentProcessor(self.fetcher, watch, filter_config, self.datastore)
        transformer = ContentTransformer()
        rule_engine = RuleEngine()

        # Get content type and stream info
        ctype_header = self.fetcher.get_all_headers().get('content-type', DEFAULT_WHEN_NO_CONTENT_TYPE_HEADER).lower()
        stream_content_type = guess_stream_type(http_content_header=ctype_header, content=self.fetcher.content)

        # Unset any existing notification error
        update_obj = {'last_notification_error': False, 'last_error': False}
        url = watch.link

        self.screenshot = self.fetcher.screenshot
        self.xpath_data = self.fetcher.xpath_data

        # Track the content type and checksum before filters
        update_obj['content_type'] = ctype_header
        update_obj['previous_md5_before_filters'] = hashlib.md5(self.fetcher.content.encode('utf-8')).hexdigest()

        # === CONTENT PREPROCESSING ===
        # Avoid creating unnecessary intermediate string copies by reassigning only when needed
        content = self.fetcher.content

        # RSS preprocessing
        if stream_content_type.is_rss:
            content = content_processor.preprocess_rss(content)
            if self.datastore.data["settings"]["application"].get("rss_reader_mode"):
                # Now just becomes regular HTML that can have xpath/CSS applied (first of the set etc)
                stream_content_type.is_rss = False
                stream_content_type.is_html = True
                self.fetcher.content = content

        # PDF preprocessing
        if watch.is_pdf or stream_content_type.is_pdf:
            content = content_processor.preprocess_pdf(raw_content=self.fetcher.raw_content)
            stream_content_type.is_html = True

        # JSON - Always reformat it nicely for consistency.

        if stream_content_type.is_json:
            if not filter_config.has_include_json_filters:
                content = content_processor.preprocess_json(raw_content=content)
        #else, otherwise it gets sorted/formatted in the filter stage anyway

        # HTML obfuscation workarounds
        if stream_content_type.is_html:
            content = html_tools.workarounds_for_obfuscations(content)

        # Check for LD+JSON price data (for HTML content)
        if stream_content_type.is_html:
            update_obj['has_ldjson_price_data'] = html_tools.has_ldjson_product_info(content)

        # === FILTER APPLICATION ===
        # Start with content reference, avoid copy until modification
        html_content = content

        # Apply include filters (CSS, XPath, JSON)
        # Except for plaintext (incase they tried to confuse the system, it will HTML escape
        #if not stream_content_type.is_plaintext:
        if filter_config.has_include_filters:
            html_content = content_processor.apply_include_filters(content, stream_content_type)

        # Apply subtractive selectors
        if filter_config.has_subtractive_selectors:
            html_content = content_processor.apply_subtractive_selectors(html_content)

        # === TEXT EXTRACTION ===
        if watch.is_source_type_url:
            # For source URLs, keep raw content
            stripped_text = html_content
        elif stream_content_type.is_plaintext:
            # For plaintext, keep as-is without HTML-to-text conversion
            stripped_text = html_content
        else:
            # Extract text from HTML/RSS content (not generic XML)
            if stream_content_type.is_html or stream_content_type.is_rss:
                stripped_text = content_processor.extract_text_from_html(html_content, stream_content_type)
            else:
                stripped_text = html_content

        # === TEXT TRANSFORMATIONS ===
        if watch.get('trim_text_whitespace'):
            stripped_text = transformer.trim_whitespace(stripped_text)

        # Save text before ignore filters (for diff calculation)
        text_content_before_ignored_filter = stripped_text

        # === DIFF FILTERING ===
        # If user wants specific diff types (added/removed/replaced only)
        if watch.has_special_diff_filter_options_set() and len(watch.history.keys()):
            stripped_text = self._apply_diff_filtering(watch, stripped_text, text_content_before_ignored_filter)
            if stripped_text is None:
                # No differences found, but content exists
                c = ChecksumCalculator.calculate(text_content_before_ignored_filter, ignore_whitespace=True)
                return False, {'previous_md5': c}, text_content_before_ignored_filter.encode('utf-8')


        # === EMPTY PAGE CHECK ===
        empty_pages_are_a_change = self.datastore.data['settings']['application'].get('empty_pages_are_a_change', False)
        if not stream_content_type.is_json and not empty_pages_are_a_change and len(stripped_text.strip()) == 0:
            raise content_fetchers.exceptions.ReplyWithContentButNoText(
                url=url,
                status_code=self.fetcher.get_last_status_code(),
                screenshot=self.fetcher.screenshot,
                has_filters=filter_config.has_include_filters,
                html_content=html_content,
                xpath_data=self.fetcher.xpath_data
            )

        update_obj["last_check_status"] = self.fetcher.get_last_status_code()

        # === REGEX EXTRACTION ===
        if filter_config.extract_text:
            extracted = transformer.extract_by_regex(stripped_text, filter_config.extract_text)
            stripped_text = extracted

        # === MORE TEXT TRANSFORMATIONS ===
        if watch.get('remove_duplicate_lines'):
            stripped_text = transformer.remove_duplicate_lines(stripped_text)

        if watch.get('sort_text_alphabetically'):
            stripped_text = transformer.sort_alphabetically(stripped_text)

        # === CHECKSUM CALCULATION ===
        text_for_checksuming = stripped_text

        # Apply ignore_text for checksum calculation
        if filter_config.ignore_text:
            text_for_checksuming = html_tools.strip_ignore_text(stripped_text, filter_config.ignore_text)

            # Optionally remove ignored lines from output
            strip_ignored_lines = watch.get('strip_ignored_lines')
            if strip_ignored_lines is None:
                strip_ignored_lines = self.datastore.data['settings']['application'].get('strip_ignored_lines')
            if strip_ignored_lines:
                stripped_text = text_for_checksuming

        # Calculate checksum
        ignore_whitespace = self.datastore.data['settings']['application'].get('ignore_whitespace', False)
        fetched_md5 = ChecksumCalculator.calculate(text_for_checksuming, ignore_whitespace=ignore_whitespace)

        # === BLOCKING RULES EVALUATION ===
        blocked = False

        # Check trigger_text
        if rule_engine.evaluate_trigger_text(stripped_text, filter_config.trigger_text):
            blocked = True

        # Check text_should_not_be_present
        if rule_engine.evaluate_text_should_not_be_present(stripped_text, filter_config.text_should_not_be_present):
            blocked = True

        # Check block_words (notify when words DISAPPEAR)
        if rule_engine.evaluate_block_words(stripped_text, filter_config.block_words):
            blocked = True

        # Check trigger_words (notify when words APPEAR)
        if rule_engine.evaluate_trigger_words(stripped_text, filter_config.trigger_words):
            blocked = True

        # Check custom conditions
        if rule_engine.evaluate_conditions(watch, self.datastore, stripped_text):
            blocked = True

        # === CHANGE DETECTION ===
        if blocked:
            changed_detected = False
        else:
            # Compare checksums
            if watch.get('previous_md5') != fetched_md5:
                changed_detected = True

            # Always record the new checksum
            update_obj["previous_md5"] = fetched_md5

            # On first run, initialize previous_md5
            if not watch.get('previous_md5'):
                watch['previous_md5'] = fetched_md5

        logger.debug(f"Watch UUID {watch.get('uuid')} content check - Previous MD5: {watch.get('previous_md5')}, Fetched MD5 {fetched_md5}")

        # === UNIQUE LINES CHECK ===
        if changed_detected and watch.get('check_unique_lines', False):
            has_unique_lines = watch.lines_contain_something_unique_compared_to_history(
                lines=stripped_text.splitlines(),
                ignore_whitespace=ignore_whitespace
            )

            if not has_unique_lines:
                logger.debug(f"check_unique_lines: UUID {watch.get('uuid')} didnt have anything new setting change_detected=False")
                changed_detected = False
            else:
                logger.debug(f"check_unique_lines: UUID {watch.get('uuid')} had unique content")

        # Note: Explicit cleanup is only needed here because text_json_diff handles
        # large strings (100KB-300KB for RSS/HTML). The other processors work with
        # small strings and don't need this.
        #
        # Python would clean these up automatically, but explicit `del` frees memory
        # immediately rather than waiting for function return, reducing peak memory usage.
        del content
        if 'html_content' in locals() and html_content is not stripped_text:
            del html_content
        if 'text_content_before_ignored_filter' in locals() and text_content_before_ignored_filter is not stripped_text:
            del text_content_before_ignored_filter
        if 'text_for_checksuming' in locals() and text_for_checksuming is not stripped_text:
            del text_for_checksuming

        return changed_detected, update_obj, stripped_text

    def _apply_diff_filtering(self, watch, stripped_text, text_before_filter):
        """Apply user's diff filtering preferences (show only added/removed/replaced lines)."""
        from changedetectionio import diff

        rendered_diff = diff.render_diff(
            previous_version_file_contents=watch.get_last_fetched_text_before_filters(),
            newest_version_file_contents=stripped_text,
            include_equal=False,
            include_added=watch.get('filter_text_added', True),
            include_removed=watch.get('filter_text_removed', True),
            include_replaced=watch.get('filter_text_replaced', True),
            include_change_type_prefix=False
        )

        watch.save_last_text_fetched_before_filters(text_before_filter.encode('utf-8'))

        if not rendered_diff and stripped_text:
            # No differences found
            return None

        return rendered_diff
