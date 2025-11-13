"""
Utility functions for RSS feed generation.
"""

from changedetectionio.jinja2_custom import render as jinja_render
from changedetectionio.notification.handler import apply_service_tweaks
from loguru import logger
import re


BAD_CHARS_REGEX = r'[\x00-\x08\x0B\x0C\x0E-\x1F]'


def scan_invalid_chars_in_rss(content):
    """
    Scan for invalid characters in RSS content.
    Returns True if invalid characters are found.
    """
    for match in re.finditer(BAD_CHARS_REGEX, content):
        i = match.start()
        bad_char = content[i]
        hex_value = f"0x{ord(bad_char):02x}"
        # Grab context
        start = max(0, i - 20)
        end = min(len(content), i + 21)
        context = content[start:end].replace('\n', '\\n').replace('\r', '\\r')
        logger.warning(f"Invalid char {hex_value} at pos {i}: ...{context}...")
        # First match is enough
        return True

    return False


def clean_entry_content(content):
    """
    Remove invalid characters from RSS content.
    """
    cleaned = re.sub(BAD_CHARS_REGEX, '', content)
    return cleaned


def generate_watch_guid(watch):
    """
    Generate a unique GUID for a watch RSS entry.
    """
    return f"{watch['uuid']}/{watch.last_changed}"


def generate_watch_diff_content(watch, dates, rss_content_format, datastore):
    """
    Generate HTML diff content for a watch given its history dates.
    Returns tuple of (content, watch_label).

    Args:
        watch: The watch object
        dates: List of history snapshot dates
        rss_content_format: Format for RSS content (html or text)
        datastore: The ChangeDetectionStore instance

    Returns:
        Tuple of (content, watch_label) - the rendered HTML content and watch label
    """
    from changedetectionio import diff

    # Same logic as watch-overview.html
    if datastore.data['settings']['application']['ui'].get('use_page_title_in_list') or watch.get('use_page_title_in_list'):
        watch_label = watch.label
    else:
        watch_label = watch.get('url')

    try:
        html_diff = diff.render_diff(
            previous_version_file_contents=watch.get_history_snapshot(timestamp=dates[-2]),
            newest_version_file_contents=watch.get_history_snapshot(timestamp=dates[-1]),
            include_equal=False
        )

        requested_output_format = datastore.data['settings']['application'].get('rss_content_format')
        url, html_diff, n_title = apply_service_tweaks(url='', n_body=html_diff, n_title=None, requested_output_format=requested_output_format)

    except FileNotFoundError as e:
        html_diff = f"History snapshot file for watch {watch.get('uuid')}@{watch.last_changed} - '{watch.get('title')} not found."

    # @note: We use <pre> because nearly all RSS readers render only HTML (Thunderbird for example cant do just plaintext)
    rss_template = "<pre>{{watch_label}} had a change.\n\n{{html_diff}}\n</pre>"
    if 'html' in rss_content_format:
        rss_template = "<html><body>\n<h4><a href=\"{{watch_url}}\">{{watch_label}}</a></h4>\n<p>{{html_diff}}</p>\n</body></html>\n"

    content = jinja_render(template_str=rss_template, watch_label=watch_label, html_diff=html_diff, watch_url=watch.link)

    # Out of range chars could also break feedgen
    if scan_invalid_chars_in_rss(content):
        content = clean_entry_content(content)

    return content, watch_label
