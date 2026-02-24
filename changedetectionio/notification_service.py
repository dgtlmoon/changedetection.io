#!/usr/bin/env python3

"""
Notification Service Module
Extracted from update_worker.py to provide standalone notification functionality
for both sync and async workers
"""
import datetime

import pytz
from loguru import logger
import time

from changedetectionio.notification import default_notification_format, valid_notification_formats


def _check_cascading_vars(datastore, var_name, watch):
    """
    Check notification variables in cascading priority:
    Individual watch settings > Tag settings > Global settings
    """
    from changedetectionio.notification import (
        USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH,
        default_notification_body,
        default_notification_title
    )

    # Would be better if this was some kind of Object where Watch can reference the parent datastore etc
    v = watch.get(var_name)
    if v and not watch.get('notification_muted'):
        if var_name == 'notification_format' and v == USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH:
            return datastore.data['settings']['application'].get('notification_format')

        return v

    tags = datastore.get_all_tags_for_watch(uuid=watch.get('uuid'))
    if tags:
        for tag_uuid, tag in tags.items():
            v = tag.get(var_name)
            if v and not tag.get('notification_muted'):
                return v

    if datastore.data['settings']['application'].get(var_name):
        return datastore.data['settings']['application'].get(var_name)

    # Otherwise could be defaults
    if var_name == 'notification_format':
        return USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH
    if var_name == 'notification_body':
        return default_notification_body
    if var_name == 'notification_title':
        return default_notification_title

    return None


class FormattableTimestamp(str):
    """
    A str subclass representing a formatted datetime. As a plain string it renders
    with the default format, but can also be called with a custom format argument
    in Jinja2 templates:

        {{ change_datetime }}                        → '2024-01-15 10:30:00 UTC'
        {{ change_datetime(format='%Y') }}           → '2024'
        {{ change_datetime(format='%A') }}           → 'Monday'

    Being a str subclass means it is natively JSON serializable.
    """
    _DEFAULT_FORMAT = '%Y-%m-%d %H:%M:%S %Z'

    def __new__(cls, timestamp):
        dt = datetime.datetime.fromtimestamp(int(timestamp), tz=pytz.UTC)
        local_tz = datetime.datetime.now().astimezone().tzinfo
        dt_local = dt.astimezone(local_tz)
        try:
            formatted = dt_local.strftime(cls._DEFAULT_FORMAT)
        except Exception:
            formatted = dt_local.isoformat()
        instance = super().__new__(cls, formatted)
        instance._dt = dt_local
        return instance

    def __call__(self, format=_DEFAULT_FORMAT):
        try:
            return self._dt.strftime(format)
        except Exception:
            return self._dt.isoformat()


class FormattableDiff(str):
    """
    A str subclass representing a rendered diff. As a plain string it renders
    with the default options for that variant, but can be called with custom
    arguments in Jinja2 templates:

        {{ diff }}                                    → default diff output
        {{ diff(lines=5) }}                           → truncate to 5 lines
        {{ diff(added_only=true) }}                   → only show added lines
        {{ diff(removed_only=true) }}                 → only show removed lines
        {{ diff(context=3) }}                         → 3 lines of context around changes
        {{ diff(word_diff=false) }}                   → line-level diff instead of word-level
        {{ diff(lines=10, added_only=true) }}         → combine args
        {{ diff_added(lines=5) }}                     → works on any diff_* variant too

    Being a str subclass means it is natively JSON serializable.
    """
    def __new__(cls, prev_snapshot, current_snapshot, **base_kwargs):
        if prev_snapshot or current_snapshot:
            from changedetectionio import diff as diff_module
            rendered = diff_module.render_diff(prev_snapshot, current_snapshot, **base_kwargs)
        else:
            rendered = ''
        instance = super().__new__(cls, rendered)
        instance._prev = prev_snapshot
        instance._current = current_snapshot
        instance._base_kwargs = base_kwargs
        return instance

    def __call__(self, lines=None, added_only=False, removed_only=False, context=0,
                 word_diff=None, case_insensitive=False, ignore_junk=False):
        from changedetectionio import diff as diff_module
        kwargs = dict(self._base_kwargs)

        if added_only:
            kwargs['include_removed'] = False
        if removed_only:
            kwargs['include_added'] = False
        if context:
            kwargs['context_lines'] = int(context)
        if word_diff is not None:
            kwargs['word_diff'] = bool(word_diff)
        if case_insensitive:
            kwargs['case_insensitive'] = True
        if ignore_junk:
            kwargs['ignore_junk'] = True

        result = diff_module.render_diff(self._prev or '', self._current or '', **kwargs)

        if lines is not None:
            result = '\n'.join(result.splitlines()[:int(lines)])

        return result


# What is passed around as notification context, also used as the complete list of valid {{ tokens }}
class NotificationContextData(dict):
    def __init__(self, initial_data=None, **kwargs):
        super().__init__({
            'base_url': None,
            'change_datetime': FormattableTimestamp(time.time()),
            'current_snapshot': None,
            'diff': FormattableDiff('', ''),
            'diff_clean': FormattableDiff('', '', include_change_type_prefix=False),
            'diff_added': FormattableDiff('', '', include_removed=False),
            'diff_added_clean': FormattableDiff('', '', include_removed=False, include_change_type_prefix=False),
            'diff_full': FormattableDiff('', '', include_equal=True),
            'diff_full_clean': FormattableDiff('', '', include_equal=True, include_change_type_prefix=False),
            'diff_patch': FormattableDiff('', '', patch_format=True),
            'diff_removed': FormattableDiff('', '', include_added=False),
            'diff_removed_clean': FormattableDiff('', '', include_added=False, include_change_type_prefix=False),
            'diff_url': None,
            'markup_text_links_to_html_links': False, # If automatic conversion of plaintext to HTML should happen
            'notification_timestamp': time.time(),
            'preview_url': None,
            'screenshot': None,
            'triggered_text': None,
            'timestamp_from': None,
            'timestamp_to': None,
            'uuid': 'XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX',  # Converted to 'watch_uuid' in create_notification_parameters
            'watch_mime_type': None,
            'watch_tag': None,
            'watch_title': None,
            'watch_url': 'https://WATCH-PLACE-HOLDER/',
        })

        # Apply any initial data passed in
        self.update({'watch_uuid': self.get('uuid')})
        if initial_data:
            self.update(initial_data)

        # Apply any keyword arguments
        if kwargs:
            self.update(kwargs)

        n_format = self.get('notification_format')
        if n_format and not valid_notification_formats.get(n_format):
            raise ValueError(f'Invalid notification format: "{n_format}"')

    def set_random_for_validation(self):
        import random, string
        """Randomly fills all dict keys with random strings (for validation/testing). 
        So we can test the output in the notification body
        """
        for key in self.keys():
            if key in ['uuid', 'time', 'watch_uuid', 'change_datetime'] or key.startswith('diff'):
                continue
            rand_str = 'RANDOM-PLACEHOLDER-'+''.join(random.choices(string.ascii_letters + string.digits, k=12))
            self[key] = rand_str

    def __setitem__(self, key, value):
        if key == 'notification_format' and isinstance(value, str) and not value.startswith('RANDOM-PLACEHOLDER-'):
            if not valid_notification_formats.get(value):
                raise ValueError(f'Invalid notification format: "{value}"')

        super().__setitem__(key, value)

def timestamp_to_localtime(timestamp):
    # Format the date using locale-aware formatting with timezone
    dt = datetime.datetime.fromtimestamp(int(timestamp))
    dt = dt.replace(tzinfo=pytz.UTC)

    # Get local timezone-aware datetime
    local_tz = datetime.datetime.now().astimezone().tzinfo
    local_dt = dt.astimezone(local_tz)

    # Format date with timezone - using strftime for locale awareness
    try:
        formatted_date = local_dt.strftime('%Y-%m-%d %H:%M:%S %Z')
    except:
        # Fallback if locale issues
        formatted_date = local_dt.isoformat()

    return formatted_date

def add_rendered_diff_to_notification_vars(notification_scan_text:str, prev_snapshot:str, current_snapshot:str, word_diff:bool):
    """
    Efficiently renders only the diff placeholders that are actually used in the notification text.

    Scans the notification template for diff placeholder usage (diff, diff_added, diff_clean, etc.)
    and only renders those specific variants, avoiding expensive render_diff() calls for unused placeholders.
    Uses LRU caching to avoid duplicate renders when multiple placeholders share the same arguments.

    Args:
        notification_scan_text: The notification template text to scan for placeholders
        prev_snapshot: Previous version of content for diff comparison
        current_snapshot: Current version of content for diff comparison
        word_diff: Whether to use word-level (True) or line-level (False) diffing

    Returns:
        dict: Only the diff placeholders that were found in notification_scan_text, with rendered content
    """
    import re

    now = time.time()

    # Define base kwargs for each diff variant — these become the stored defaults
    # on the FormattableDiff object, so {{ diff(lines=5) }} overrides on top of them
    diff_specs = {
        'diff': {'word_diff': word_diff},
        'diff_clean': {'word_diff': word_diff, 'include_change_type_prefix': False},
        'diff_added': {'word_diff': word_diff, 'include_removed': False},
        'diff_added_clean': {'word_diff': word_diff, 'include_removed': False, 'include_change_type_prefix': False},
        'diff_full': {'word_diff': word_diff, 'include_equal': True},
        'diff_full_clean': {'word_diff': word_diff, 'include_equal': True, 'include_change_type_prefix': False},
        'diff_patch': {'word_diff': word_diff, 'patch_format': True},
        'diff_removed': {'word_diff': word_diff, 'include_added': False},
        'diff_removed_clean': {'word_diff': word_diff, 'include_added': False, 'include_change_type_prefix': False},
    }

    ret = {}
    rendered_count = 0
    # Only create FormattableDiff objects for diff keys actually used in the notification text
    for key in NotificationContextData().keys():
        if key.startswith('diff') and key in diff_specs:
            # Check if this placeholder is actually used in the notification text
            pattern = rf"(?<![A-Za-z0-9_]){re.escape(key)}(?![A-Za-z0-9_])"
            if re.search(pattern, notification_scan_text, re.IGNORECASE):
                ret[key] = FormattableDiff(prev_snapshot, current_snapshot, **diff_specs[key])
                rendered_count += 1

    if rendered_count:
        logger.trace(f"Rendered {rendered_count} diff placeholder(s) {sorted(ret.keys())} in {time.time() - now:.3f}s")

    return ret

def set_basic_notification_vars(current_snapshot, prev_snapshot, watch, triggered_text, timestamp_changed=None):

    n_object = {
        'current_snapshot': current_snapshot,
        'prev_snapshot': prev_snapshot,
        'screenshot': watch.get_screenshot() if watch and watch.get('notification_screenshot') else None,
        'change_datetime': FormattableTimestamp(timestamp_changed) if timestamp_changed else None,
        'triggered_text': triggered_text,
        'uuid': watch.get('uuid') if watch else None,
        'watch_url': watch.get('url') if watch else None,
        'watch_uuid': watch.get('uuid') if watch else None,
        'watch_mime_type': watch.get('content-type')
    }

    # The \n's in the content from the above will get converted to <br> etc depending on the notification format

    if watch:
        n_object.update(watch.extra_notification_token_values())

    return n_object

class NotificationService:
    """
    Standalone notification service that handles all notification functionality
    previously embedded in the update_worker class
    """
    
    def __init__(self, datastore, notification_q):
        self.datastore = datastore
        self.notification_q = notification_q
    
    def queue_notification_for_watch(self, n_object: NotificationContextData, watch, date_index_from=-2, date_index_to=-1):
        """
        Queue a notification for a watch with full diff rendering and template variables
        """
        from changedetectionio.notification import USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH

        if not isinstance(n_object, NotificationContextData):
            raise TypeError(f"Expected NotificationContextData, got {type(n_object)}")

        dates = []
        trigger_text = ''

        if watch:
            watch_history = watch.history
            dates = list(watch_history.keys())
            trigger_text = watch.get('trigger_text', [])

        # Add text that was triggered
        if len(dates):
            snapshot_contents = watch.get_history_snapshot(timestamp=dates[-1])
        else:
            snapshot_contents = "No snapshot/history available, the watch should fetch atleast once."

        # If we ended up here with "System default"
        if n_object.get('notification_format') == USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH:
            n_object['notification_format'] = self.datastore.data['settings']['application'].get('notification_format')


        triggered_text = ''
        if len(trigger_text):
            from . import html_tools
            triggered_text = html_tools.get_triggered_text(content=snapshot_contents, trigger_text=trigger_text)
            if triggered_text:
                triggered_text = '\n'.join(triggered_text)

        # Could be called as a 'test notification' with only 1 snapshot available
        prev_snapshot = "Example text: example test\nExample text: change detection is cool\nExample text: some more examples\n"
        current_snapshot = "Example text: example test\nExample text: change detection is fantastic\nExample text: even more examples\nExample text: a lot more examples"

        if len(dates) > 1:
            prev_snapshot = watch.get_history_snapshot(timestamp=dates[date_index_from])
            current_snapshot = watch.get_history_snapshot(timestamp=dates[date_index_to])


        n_object.update(set_basic_notification_vars(current_snapshot=current_snapshot,
                                                    prev_snapshot=prev_snapshot,
                                                    watch=watch,
                                                    triggered_text=triggered_text,
                                                    timestamp_changed=dates[date_index_to]))

        if self.notification_q:
            logger.debug("Queued notification for sending")
            self.notification_q.put(n_object)
        else:
            logger.debug("Not queued, no queue defined. Just returning processed data")
            return n_object

    def send_content_changed_notification(self, watch_uuid):
        """
        Send notification when content changes are detected
        """
        n_object = NotificationContextData()
        watch = self.datastore.data['watching'].get(watch_uuid)
        if not watch:
            return

        watch_history = watch.history
        dates = list(watch_history.keys())
        # Theoretically it's possible that this could be just 1 long,
        # - In the case that the timestamp key was not unique
        if len(dates) == 1:
            raise ValueError(
                "History index had 2 or more, but only 1 date loaded, timestamps were not unique? maybe two of the same timestamps got written, needs more delay?"
            )

        # Should be a better parent getter in the model object

        # Prefer - Individual watch settings > Tag settings >  Global settings (in that order)
        # this change probably not needed?
        n_object['notification_urls'] = _check_cascading_vars(self.datastore, 'notification_urls', watch)
        n_object['notification_title'] = _check_cascading_vars(self.datastore,'notification_title', watch)
        n_object['notification_body'] = _check_cascading_vars(self.datastore,'notification_body', watch)
        n_object['notification_format'] = _check_cascading_vars(self.datastore,'notification_format', watch)

        # (Individual watch) Only prepare to notify if the rules above matched
        queued = False
        if n_object and n_object.get('notification_urls'):
            queued = True

            count = watch.get('notification_alert_count', 0) + 1
            self.datastore.update_watch(uuid=watch_uuid, update_obj={'notification_alert_count': count})

            self.queue_notification_for_watch(n_object=n_object, watch=watch)

        return queued

    def send_filter_failure_notification(self, watch_uuid):
        """
        Send notification when CSS/XPath filters fail consecutively
        """
        threshold = self.datastore.data['settings']['application'].get('filter_failure_notification_threshold_attempts')
        watch = self.datastore.data['watching'].get(watch_uuid)
        if not watch:
            return

        filter_list = ", ".join(watch['include_filters'])
        # @todo - This could be a markdown template on the disk, apprise will convert the markdown to HTML+Plaintext parts in the email, and then 'markup_text_links_to_html_links' is not needed
        body = f"""Hello,

Your configured CSS/xPath filters of '{filter_list}' for {{{{watch_url}}}} did not appear on the page after {threshold} attempts.

It's possible the page changed layout and the filter needs updating ( Try the 'Visual Selector' tab )

Edit link: {{{{base_url}}}}/edit/{{{{watch_uuid}}}}

Thanks - Your omniscient changedetection.io installation.
"""

        n_object = NotificationContextData({
            'notification_title': 'Changedetection.io - Alert - CSS/xPath filter was not present in the page',
            'notification_body': body,
            'notification_format': _check_cascading_vars(self.datastore, 'notification_format', watch),
        })
        n_object['markup_text_links_to_html_links'] = n_object.get('notification_format').startswith('html')

        if len(watch['notification_urls']):
            n_object['notification_urls'] = watch['notification_urls']

        elif len(self.datastore.data['settings']['application']['notification_urls']):
            n_object['notification_urls'] = self.datastore.data['settings']['application']['notification_urls']

        # Only prepare to notify if the rules above matched
        if 'notification_urls' in n_object:
            n_object.update({
                'watch_url': watch['url'],
                'uuid': watch_uuid,
                'screenshot': None
            })
            self.notification_q.put(n_object)
            logger.debug(f"Sent filter not found notification for {watch_uuid}")
        else:
            logger.debug(f"NOT sending filter not found notification for {watch_uuid} - no notification URLs")

    def send_step_failure_notification(self, watch_uuid, step_n):
        """
        Send notification when browser steps fail consecutively
        """
        watch = self.datastore.data['watching'].get(watch_uuid, False)
        if not watch:
            return
        threshold = self.datastore.data['settings']['application'].get('filter_failure_notification_threshold_attempts')

        step = step_n + 1
        # @todo - This could be a markdown template on the disk, apprise will convert the markdown to HTML+Plaintext parts in the email, and then 'markup_text_links_to_html_links' is not needed

        # {{{{ }}}} because this will be Jinja2 {{ }} tokens
        body = f"""Hello,
        
Your configured browser step at position {step} for the web page watch {{{{watch_url}}}} did not appear on the page after {threshold} attempts, did the page change layout?

The element may have moved and needs editing, or does it need a delay added?

Edit link: {{{{base_url}}}}/edit/{{{{watch_uuid}}}}

Thanks - Your omniscient changedetection.io installation.
"""

        n_object = NotificationContextData({
            'notification_title': f"Changedetection.io - Alert - Browser step at position {step} could not be run",
            'notification_body': body,
            'notification_format': self._check_cascading_vars('notification_format', watch),
        })
        n_object['markup_text_links_to_html_links'] = n_object.get('notification_format').startswith('html')

        if len(watch['notification_urls']):
            n_object['notification_urls'] = watch['notification_urls']

        elif len(self.datastore.data['settings']['application']['notification_urls']):
            n_object['notification_urls'] = self.datastore.data['settings']['application']['notification_urls']

        # Only prepare to notify if the rules above matched
        if 'notification_urls' in n_object:
            n_object.update({
                'watch_url': watch['url'],
                'uuid': watch_uuid
            })
            self.notification_q.put(n_object)
            logger.error(f"Sent step not found notification for {watch_uuid}")


# Convenience functions for creating notification service instances
def create_notification_service(datastore, notification_q):
    """
    Factory function to create a NotificationService instance
    """
    return NotificationService(datastore, notification_q)