import os

import uuid as uuid_builder

minimum_seconds_recheck_time = int(os.getenv('MINIMUM_SECONDS_RECHECK_TIME', 60))

from changedetectionio.notification import (
    default_notification_body,
    default_notification_format,
    default_notification_title,
)


class model(dict):
    base_config = {
            'url': None,
            'tag': None,
            'last_checked': 0,
            'last_changed': 0,
            'paused': False,
            'last_viewed': 0,  # history key value of the last viewed via the [diff] link
            'newest_history_key': 0,
            'title': None,
            'previous_md5': False,
#           UUID not needed, should be generated only as a key
#            'uuid':
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
            'proxy': None, # Preferred proxy connection
            # Re #110, so then if this is set to None, we know to use the default value instead
            # Requires setting to None on submit if it's the same as the default
            # Should be all None by default, so we use the system default in this case.
            'time_between_check': {'weeks': None, 'days': None, 'hours': None, 'minutes': None, 'seconds': None}
        }

    def __init__(self, *arg, **kw):
        self.update(self.base_config)
        # goes at the end so we update the default object with the initialiser
        super(model, self).__init__(*arg, **kw)


    @property
    def has_empty_checktime(self):
        # using all() + dictionary comprehension
        # Check if all values are 0 in dictionary
        res = all(x == None or x == False or x==0 for x in self.get('time_between_check', {}).values())
        return res

    def threshold_seconds(self):
        seconds = 0
        mtable = {'seconds': 1, 'minutes': 60, 'hours': 3600, 'days': 86400, 'weeks': 86400 * 7}
        for m, n in mtable.items():
            x = self.get('time_between_check', {}).get(m, None)
            if x:
                seconds += x * n
        return seconds
