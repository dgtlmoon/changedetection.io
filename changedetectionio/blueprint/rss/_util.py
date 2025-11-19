"""
Utility functions for RSS feed generation.
"""

from changedetectionio.notification.handler import process_notification
from changedetectionio.notification_service import NotificationContextData, _check_cascading_vars
from loguru import logger
import datetime
import pytz
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


def validate_rss_token(datastore, request):
    """
    Validate the RSS access token from the request.

    Returns:
        tuple: (is_valid, error_response) where error_response is None if valid
    """
    app_rss_token = datastore.data['settings']['application'].get('rss_access_token')
    rss_url_token = request.args.get('token')

    if rss_url_token != app_rss_token:
        return False, ("Access denied, bad token", 403)

    return True, None


def get_rss_template(datastore, watch, rss_content_format, default_html, default_plaintext):
    """Get the appropriate template for RSS content."""
    if datastore.data['settings']['application'].get('rss_template_type') == 'notification_body':
        return _check_cascading_vars(datastore=datastore, var_name='notification_body', watch=watch)

    override = datastore.data['settings']['application'].get('rss_template_override')
    if override and override.strip():
        return override
    elif 'text' in rss_content_format:
        return default_plaintext
    else:
        return default_html


def get_watch_label(datastore, watch):
    """Get the label for a watch based on settings."""
    if datastore.data['settings']['application']['ui'].get('use_page_title_in_list') or watch.get('use_page_title_in_list'):
        return watch.label
    else:
        return watch.get('url')


def add_watch_categories(fe, watch, datastore):
    """Add category tags to a feed entry based on watch tags."""
    for tag_uuid in watch.get('tags', []):
        tag = datastore.data['settings']['application'].get('tags', {}).get(tag_uuid)
        if tag and tag.get('title'):
            fe.category(term=tag.get('title'))


def build_notification_context(watch, timestamp_from, timestamp_to, watch_label,
                               n_body_template, rss_content_format):
    """Build the notification context object."""
    return NotificationContextData(initial_data={
        'notification_urls': ['null://just-sending-a-null-test-for-the-render-in-RSS'],
        'notification_body': n_body_template,
        'timestamp_to': timestamp_to,
        'timestamp_from': timestamp_from,
        'watch_label': watch_label,
        'notification_format': rss_content_format
    })


def render_notification(n_object, notification_service, watch, datastore,
                       date_index_from=None, date_index_to=None):
    """Process and render the notification content."""
    kwargs = {'n_object': n_object, 'watch': watch}

    if date_index_from is not None and date_index_to is not None:
        kwargs['date_index_from'] = date_index_from
        kwargs['date_index_to'] = date_index_to

    n_object = notification_service.queue_notification_for_watch(**kwargs)
    n_object['watch_mime_type'] = None

    res = process_notification(n_object=n_object, datastore=datastore)
    return res[0]


def populate_feed_entry(fe, watch, content, guid, timestamp, link=None, title_suffix=None):
    """Populate a feed entry with content and metadata."""
    watch_label = watch.get('url')  # Already determined by caller

    # Set link
    if link:
        fe.link(link=link)

    # Set title
    if title_suffix:
        fe.title(title=f"{watch_label} - {title_suffix}")
    else:
        fe.title(title=watch_label)

    # Clean and set content
    if scan_invalid_chars_in_rss(content):
        content = clean_entry_content(content)
    fe.content(content=content, type='CDATA')

    # Set GUID
    fe.guid(guid, permalink=False)

    # Set pubDate using the timestamp of this specific change
    dt = datetime.datetime.fromtimestamp(int(timestamp))
    dt = dt.replace(tzinfo=pytz.UTC)
    fe.pubDate(dt)

