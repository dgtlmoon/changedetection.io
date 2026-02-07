import os
import uuid

from changedetectionio import strtobool
USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH = 'System default'
CONDITIONS_MATCH_LOGIC_DEFAULT = 'ALL'

class watch_base(dict):
    """
    Base watch domain model (inherits from dict for backward compatibility).

    WARNING: This class inherits from dict, which violates proper encapsulation.
    Dict inheritance is legacy technical debt that should be refactored to a proper
    domain model (e.g., Pydantic BaseModel) for better type safety and validation.

    TODO: Migrate to Pydantic BaseModel or dataclass for:
          - Type safety and IDE autocomplete
          - Automatic validation
          - Clear separation between domain model and serialization
          - Immutability options
          - Better testing

    Core Fields:
        uuid (str): Unique identifier for this watch (auto-generated)
        url (str): Target URL to monitor for changes
        title (str|None): Custom display name (overrides page_title if set)
        page_title (str|None): Title extracted from <title> tag of monitored page
        tags (List[str]): List of tag UUIDs for categorization
        tag (str): DEPRECATED - Old single-tag system, use tags instead

    Check Configuration:
        processor (str): Processor type ('text_json_diff', 'restock_diff', etc.)
        fetch_backend (str): Fetcher to use ('system', 'html_requests', 'playwright', etc.)
        method (str): HTTP method ('GET', 'POST', etc.)
        headers (dict): Custom HTTP headers to send
        proxy (str|None): Preferred proxy server
        paused (bool): Whether change detection is paused

    Scheduling:
        time_between_check (dict): Check interval {'weeks': int, 'days': int, 'hours': int, 'minutes': int, 'seconds': int}
        time_between_check_use_default (bool): Use global default interval if True
        time_schedule_limit (dict): Weekly schedule limiting when checks can run
            Structure: {
                'enabled': bool,
                'monday/tuesday/.../sunday': {
                    'enabled': bool,
                    'start_time': str ('HH:MM'),
                    'duration': {'hours': str, 'minutes': str}
                }
            }

    Content Filtering:
        include_filters (List[str]): CSS/XPath selectors to extract content
        subtractive_selectors (List[str]): Selectors to remove from content
        ignore_text (List[str]): Text patterns to ignore in change detection
        trigger_text (List[str]): Text/regex that must be present to trigger change
        text_should_not_be_present (List[str]): Text that should NOT be present
        extract_text (List[str]): Regex patterns to extract specific text after filtering

    Text Processing:
        trim_text_whitespace (bool): Strip leading/trailing whitespace
        sort_text_alphabetically (bool): Sort lines alphabetically before comparison
        remove_duplicate_lines (bool): Remove duplicate lines
        check_unique_lines (bool): Compare against all history for unique lines
        strip_ignored_lines (bool|None): Remove lines matching ignore patterns

    Change Detection Filters:
        filter_text_added (bool): Include added text in change detection
        filter_text_removed (bool): Include removed text in change detection
        filter_text_replaced (bool): Include replaced text in change detection

    Browser Automation:
        browser_steps (List[dict]): Browser automation steps for JS-heavy sites
        browser_steps_last_error_step (int|None): Last step that caused error
        webdriver_delay (int|None): Seconds to wait after page load
        webdriver_js_execute_code (str|None): JavaScript to execute before extraction

    Restock Detection:
        in_stock_only (bool): Only trigger on in-stock transitions
        follow_price_changes (bool): Monitor price changes
        has_ldjson_price_data (bool|None): Whether page has LD-JSON price data
        track_ldjson_price_data (str|None): Track LD-JSON price data ('ACCEPT', 'REJECT', None)
        price_change_threshold_percent (float|None): Minimum price change % to trigger

    Notifications:
        notification_urls (List[str]): Apprise URLs for notifications
        notification_title (str|None): Custom notification title template
        notification_body (str|None): Custom notification body template
        notification_format (str): Notification format (e.g., 'System default', 'Text', 'HTML')
        notification_muted (bool): Disable notifications for this watch
        notification_screenshot (bool): Include screenshot in notifications
        notification_alert_count (int): Number of notifications sent
        last_notification_error (str|None): Last notification error message
        body (str|None): DEPRECATED? Legacy notification body field
        filter_failure_notification_send (bool): Send notification on filter failures

    History & State:
        date_created (int|None): Unix timestamp of watch creation
        last_checked (int): Unix timestamp of last check
        last_viewed (int): History snapshot key of last user view
        last_error (str|bool): Last error message or False if no error
        check_count (int): Total number of checks performed
        fetch_time (float): Duration of last fetch in seconds
        consecutive_filter_failures (int): Counter for consecutive filter match failures
        previous_md5 (str|bool): MD5 hash of previous content
        previous_md5_before_filters (str|bool): MD5 hash before filters applied
        history_snapshot_max_length (int|None): Max history snapshots to keep (None = use global)

    Conditions:
        conditions (dict): Custom conditions for change detection logic
        conditions_match_logic (str): Logic operator ('ALL', 'ANY') for conditions

    Metadata:
        content-type (str|None): Content-Type from last fetch
        remote_server_reply (str|None): Server header from last response
        ignore_status_codes (List[int]|None): HTTP status codes to ignore
        use_page_title_in_list (bool|None): Display page title in watch list (None = use system default)

    Instance Attributes (not serialized):
        __datastore: Reference to parent DataStore (set externally after creation)
        watch_data_dir: Filesystem path for this watch's data directory

    Notes:
        - Many fields default to None to distinguish "not set" from "set to default"
        - When field is None, system-level defaults are used
        - Processor-specific configs (e.g., processor_config_*) are NOT stored in watch.json
          They are stored in separate {processor_name}.json files
        - This class is used for both Watch and Tag objects (tags reuse the structure)
    """

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
            'history_snapshot_max_length': None,
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

    def __deepcopy__(self, memo):
        """
        Custom deepcopy for all watch_base subclasses (Watch, Tag, etc.).

        CRITICAL FIX: Prevents copying large reference objects like __datastore
        which would cause exponential memory growth when Watch objects are deepcopied.

        This is called by:
        - api/Watch.py:76 (API endpoint)
        - api/Tags.py:28 (Tags API)
        - processors/base.py:26 (EVERY processor run)
        - store/__init__.py:544 (clone watch)
        - And other locations
        """
        from copy import deepcopy

        # Create new instance without calling __init__
        cls = self.__class__
        new_obj = cls.__new__(cls)
        memo[id(self)] = new_obj

        # Copy the dict data (all the settings)
        for key, value in self.items():
            new_obj[key] = deepcopy(value, memo)

        # Copy instance attributes dynamically
        # This handles Watch-specific attrs (like __datastore) and any future subclass attrs
        for attr_name in dir(self):
            # Skip methods, special attrs, and dict keys
            if attr_name.startswith('_') and not attr_name.startswith('__'):
                # This catches _model__datastore, _model__history_n, etc.
                try:
                    attr_value = getattr(self, attr_name)

                    # Special handling: Share references to large objects instead of copying
                    # Examples: __datastore, __app_reference, __global_settings, etc.
                    if attr_name.endswith('__datastore') or attr_name.endswith('__app'):
                        # Share the reference (don't copy!) to prevent memory leaks
                        setattr(new_obj, attr_name, attr_value)
                    # Skip cache attributes - let them regenerate on demand
                    elif 'cache' in attr_name.lower():
                        pass  # Don't copy caches
                    # Copy regular instance attributes
                    elif not callable(attr_value):
                        setattr(new_obj, attr_name, attr_value)
                except AttributeError:
                    pass  # Attribute doesn't exist in this instance

        return new_obj

    def __getstate__(self):
        """
        Custom pickle serialization for all watch_base subclasses.

        Excludes large reference objects (like __datastore) from serialization.
        """
        # Get the dict data
        state = dict(self)

        # Collect instance attributes (excluding methods and large references)
        instance_attrs = {}
        for attr_name in dir(self):
            if attr_name.startswith('_') and not attr_name.startswith('__'):
                try:
                    attr_value = getattr(self, attr_name)
                    # Exclude large reference objects and caches from serialization
                    if not (attr_name.endswith('__datastore') or
                           attr_name.endswith('__app') or
                           'cache' in attr_name.lower() or
                           callable(attr_value)):
                        instance_attrs[attr_name] = attr_value
                except AttributeError:
                    pass

        if instance_attrs:
            state['__instance_metadata__'] = instance_attrs

        return state

    def __setstate__(self, state):
        """
        Custom pickle deserialization for all watch_base subclasses.

        WARNING: Large reference objects (like __datastore) are NOT restored!
        Caller must restore these references after unpickling if needed.
        """
        # Extract metadata
        metadata = state.pop('__instance_metadata__', {})

        # Restore dict data
        self.update(state)

        # Restore instance attributes
        for attr_name, attr_value in metadata.items():
            setattr(self, attr_name, attr_value)