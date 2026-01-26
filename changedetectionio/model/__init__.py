import os
import uuid

from changedetectionio import strtobool
USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH = 'System default'
CONDITIONS_MATCH_LOGIC_DEFAULT = 'ALL'

class watch_base(dict):

    def __init__(self, *arg, **kw):
        self.update({
            # Custom notification content
            # Re #110, so then if this is set to None, we know to use the default value instead
            # Requires setting to None on submit if it's the same as the default
            # Should be all None by default, so we use the system default in this case.
            'body': None,
            'browser_steps': [],
            'browser_steps_last_error_step': None,
            'conditions' : {},
            'conditions_match_logic': CONDITIONS_MATCH_LOGIC_DEFAULT,
            'check_count': 0,
            'check_unique_lines': False,  # On change-detected, compare against all history if its something new
            'consecutive_filter_failures': 0,  # Every time the CSS/xPath filter cannot be located, reset when all is fine.
            'content-type': None,
            'date_created': None,
            'extract_text': [],  # Extract text by regex after filters
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
            'ignore_status_codes': None,
            'in_stock_only': True,  # Only trigger change on going to instock from out-of-stock
            'include_filters': [],
            'last_checked': 0,
            'last_error': False,
            'last_notification_error': None,
            'last_viewed': 0,  # history key value of the last viewed via the [diff] link
            'method': 'GET',
            'notification_alert_count': 0,
            'notification_body': None,
            'notification_format': USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH,
            'notification_muted': False,
            'notification_screenshot': False,  # Include the latest screenshot if available and supported by the apprise URL
            'notification_title': None,
            'notification_urls': [],  # List of URLs to add to the notification Queue (Usually AppRise)
            'page_title': None, # <title> from the page
            'paused': False,
            'previous_md5': False,
            'previous_md5_before_filters': False,  # Used for skipping changedetection entirely
            'processor': 'text_json_diff',  # could be restock_diff or others from .processors
            'price_change_threshold_percent': None,
            'proxy': None,  # Preferred proxy connection
            'remote_server_reply': None,  # From 'server' reply header
            'sort_text_alphabetically': False,
            'strip_ignored_lines': None,
            'subtractive_selectors': [],
            'tag': '',  # Old system of text name for a tag, to be removed
            'tags': [],  # list of UUIDs to App.Tags
            'text_should_not_be_present': [],  # Text that should not present
            # Watch words - simplified text matching
            'block_words': [],      # Notify when these words DISAPPEAR (restock alerts)
            'trigger_words': [],    # Notify when these words APPEAR (sold out alerts)
            # Event metadata
            'artist': None,
            'venue': None,
            'event_date': None,
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
            'title': None, # An arbitrary field that overrides 'page_title'
            'track_ldjson_price_data': None,
            'trim_text_whitespace': False,
            'remove_duplicate_lines': False,
            'trigger_text': [],  # List of text or regex to wait for until a change is detected
            'url': '',
            'use_page_title_in_list': None, # None = use system settings
            'uuid': str(uuid.uuid4()),
            'webdriver_delay': None,
            'webdriver_js_execute_code': None,  # Run before change-detection
        })

        super(watch_base, self).__init__(*arg, **kw)

        if self.get('default'):
            del self['default']