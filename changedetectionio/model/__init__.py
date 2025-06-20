import os
import uuid
import json

from changedetectionio import strtobool
default_notification_format_for_watch = 'System default'

class watch_base:

    def __init__(self, *arg, **kw):
        self.__data = {
            # Custom notification content
            # Re #110, so then if this is set to None, we know to use the default value instead
            # Requires setting to None on submit if it's the same as the default
            # Should be all None by default, so we use the system default in this case.
            'body': None,
            'browser_steps': [],
            'browser_steps_last_error_step': None,
            'check_count': 0,
            'check_unique_lines': False,  # On change-detected, compare against all history if its something new
            'consecutive_filter_failures': 0,  # Every time the CSS/xPath filter cannot be located, reset when all is fine.
            'content-type': None,
            'date_created': None,
            'extract_text': [],  # Extract text by regex after filters
            'extract_title_as_title': False,
            'fetch_backend': 'system',  # plaintext, playwright etc
            'fetch_time': 0.0,
            'filter_failure_notification_send': strtobool(os.getenv('FILTER_FAILURE_NOTIFICATION_SEND_DEFAULT', 'True')),
            'filter_text_added': True,
            'filter_text_removed': True,
            'filter_text_replaced': True,
            'follow_price_changes': True,
            'has_ldjson_price_data': None,
            'headers': {},  # Extra headers to send
            'ignore_text': [],  # List of text to ignore when calculating the comparison checksum
            'in_stock_only': True,  # Only trigger change on going to instock from out-of-stock
            'include_filters': [],
            'last_checked': 0,
            'last_error': False,
            'last_notification_error': None,
            'last_viewed': 0,  # history key value of the last viewed via the [diff] link
            'method': 'GET',
            'notification_alert_count': 0,
            'notification_body': None,
            'notification_format': default_notification_format_for_watch,
            'notification_muted': False,
            'notification_screenshot': False,  # Include the latest screenshot if available and supported by the apprise URL
            'notification_title': None,
            'notification_urls': [],  # List of URLs to add to the notification Queue (Usually AppRise)
            'paused': False,
            'previous_md5': False,
            'previous_md5_before_filters': False,  # Used for skipping changedetection entirely
            'processor': 'text_json_diff',  # could be restock_diff or others from .processors
            'price_change_threshold_percent': None,
            'proxy': None,  # Preferred proxy connection
            'remote_server_reply': None,  # From 'server' reply header
            'sort_text_alphabetically': False,
            'subtractive_selectors': [],
            'tag': '',  # Old system of text name for a tag, to be removed
            'tags': [],  # list of UUIDs to App.Tags
            'text_should_not_be_present': [],  # Text that should not present
            'time_between_check': {'weeks': None, 'days': None, 'hours': None, 'minutes': None, 'seconds': None},
            'time_between_check_use_default': True,
            "time_schedule_limit": {
                "enabled": False,
                "monday": {
                    "enabled": True,
                    "start_time": "00:00",
                    "duration": {
                        "hours": "24",
                        "minutes": "00"
                    }
                },
                "tuesday": {
                    "enabled": True,
                    "start_time": "00:00",
                    "duration": {
                        "hours": "24",
                        "minutes": "00"
                    }
                },
                "wednesday": {
                    "enabled": True,
                    "start_time": "00:00",
                    "duration": {
                        "hours": "24",
                        "minutes": "00"
                    }
                },
                "thursday": {
                    "enabled": True,
                    "start_time": "00:00",
                    "duration": {
                        "hours": "24",
                        "minutes": "00"
                    }
                },
                "friday": {
                    "enabled": True,
                    "start_time": "00:00",
                    "duration": {
                        "hours": "24",
                        "minutes": "00"
                    }
                },
                "saturday": {
                    "enabled": True,
                    "start_time": "00:00",
                    "duration": {
                        "hours": "24",
                        "minutes": "00"
                    }
                },
                "sunday": {
                    "enabled": True,
                    "start_time": "00:00",
                    "duration": {
                        "hours": "24",
                        "minutes": "00"
                    }
                },
            },
            'title': None,
            'track_ldjson_price_data': None,
            'trim_text_whitespace': False,
            'remove_duplicate_lines': False,
            'trigger_text': [],  # List of text or regex to wait for until a change is detected
            'url': '',
            'uuid': str(uuid.uuid4()),
            'webdriver_delay': None,
            'webdriver_js_execute_code': None,  # Run before change-detection
        }
        
        if len(arg) == 1 and (isinstance(arg[0], dict) or hasattr(arg[0], 'keys')):
            self.__data.update(arg[0])
        if kw:
            self.__data.update(kw)

        if self.__data.get('default'):
            del self.__data['default']

    def __getitem__(self, key):
        return self.__data[key]

    def __setitem__(self, key, value):
        self.__data[key] = value

    def __delitem__(self, key):
        del self.__data[key]

    def __iter__(self):
        return iter(self.__data)

    def __len__(self):
        return len(self.__data)

    def __contains__(self, key):
        return key in self.__data

    def __repr__(self):
        return repr(self.__data)

    def __str__(self):
        return str(self.__data)

    def keys(self):
        return self.__data.keys()

    def values(self):
        return self.__data.values()

    def items(self):
        return self.__data.items()

    def get(self, key, default=None):
        return self.__data.get(key, default)

    def pop(self, key, *args):
        return self.__data.pop(key, *args)

    def popitem(self):
        return self.__data.popitem()

    def clear(self):
        self.__data.clear()

    def update(self, *args, **kwargs):
        self.__data.update(*args, **kwargs)

    def setdefault(self, key, default=None):
        return self.__data.setdefault(key, default)

    def copy(self):
        return self.__data.copy()

    def __deepcopy__(self, memo):
        from copy import deepcopy
        new_instance = self.__class__()
        new_instance.__data = deepcopy(self.__data, memo)
        return new_instance

    def __reduce__(self):
        return (self.__class__, (self.__data,))

    def to_dict(self):
        return dict(self.__data)