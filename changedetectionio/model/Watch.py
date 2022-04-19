import os

import uuid as uuid_builder

minimum_seconds_recheck_time = int(os.getenv('MINIMUM_SECONDS_RECHECK_TIME', 5))

from changedetectionio.notification import (
    default_notification_body,
    default_notification_format,
    default_notification_title,
)


class model(dict):
    def __init__(self, *arg, **kw):
        super(model, self).__init__(*arg, **kw)
        self.update({
            'url': None,
            'tag': None,
            'last_checked': 0,
            'last_changed': 0,
            'paused': False,
            'last_viewed': 0,  # history key value of the last viewed via the [diff] link
            'newest_history_key': "",
            'title': None,
            'previous_md5': "",
            'uuid': str(uuid_builder.uuid4()),
            'headers': {},  # Extra headers to send
            'body': None,
            'method': 'GET',
            'history': {},  # Dict of timestamp and output stripped filename
            'ignore_text': [],  # List of text to ignore when calculating the comparison checksum
            # Custom notification content
            'notification_urls': [],  # List of URLs to add to the notification Queue (Usually AppRise)
            'notification_title': default_notification_title,
            'notification_body': default_notification_body,
            'notification_format': default_notification_format,
            'css_filter': "",
            'subtractive_selectors': [],
            'trigger_text': [],  # List of text or regex to wait for until a change is detected
            'fetch_backend': None,
            'extract_title_as_title': False,
            # Re #110, so then if this is set to None, we know to use the default value instead
            # Requires setting to None on submit if it's the same as the default
            # Should be all None by default, so we use the system default in this case.
            'minutes_between_check': None
        })

    @property
    def has_empty_checktime(self):
        if self.get('minutes_between_check', None):
            return False
        return True

    @property
    def threshold_seconds(self):
        sec = self.get('minutes_between_check', None)
        if sec:
            sec = sec * 60
        return sec
