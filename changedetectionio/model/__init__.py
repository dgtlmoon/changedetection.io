import os
import uuid

from changedetectionio import strtobool
from .persistence import EntityPersistenceMixin, _determine_entity_type

__all__ = ['EntityPersistenceMixin', 'watch_base']

from ..browser_steps.browser_steps import browser_steps_get_valid_steps

USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH = 'System default'
CONDITIONS_MATCH_LOGIC_DEFAULT = 'ALL'


class watch_base(dict):
    """
    Base watch domain model (inherits from dict for backward compatibility).

    WARNING: This class inherits from dict, which violates proper encapsulation.
    Dict inheritance is legacy technical debt that should be refactored to a proper
    domain model (e.g., Pydantic BaseModel) for better type safety and validation.

    TODO: Migrate to Pydantic BaseModel for:
          - Type safety and IDE autocomplete
          - Automatic validation
          - Clear separation between domain model and serialization
          - Database backend abstraction (file → postgres → mongodb)
          - Configuration override chain resolution (Watch → Tag → Global)
          - Immutability options
          - Better testing
          - USE https://docs.pydantic.dev/latest/integrations/datamodel_code_generator TO BUILD THE MODEL FROM THE API-SPEC!!!

    CHAIN RESOLUTION ARCHITECTURE:
        The dream is a 3-level override hierarchy:
            Watch settings → Tag/Group settings → Global settings

        Current implementation: MANUAL resolution scattered across codebase
        - Processors manually check watch.get('field')
        - Loop through tags to find overrides_watch=True
        - Fall back to datastore['settings']['application']['field']

        Pydantic implementation: AUTOMATIC resolution via @computed_field
        - Single source of truth for each setting's resolution logic
        - Type-safe, testable, self-documenting
        - Example: watch.resolved_fetch_backend (instead of nested dict navigation)

        See: Watch.py model docstring for detailed Pydantic architecture plan
        See: Tag.py model docstring for tag override explanation
        See: processors/restock_diff/processor.py:184-192 for current manual example

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
        data_dir: Filesystem path for this watch's data directory

    Notes:
        - Many fields default to None to distinguish "not set" from "set to default"
        - When field is None, system-level defaults are used
        - Processor-specific configs (e.g., processor_config_*) are NOT stored in watch.json
          They are stored in separate {processor_name}.json files
        - This class is used for both Watch and Tag objects (tags reuse the structure)
    """

    def __init__(self, *arg, **kw):
        # Store datastore reference (common to Watch and Tag)
        # Use single underscore to avoid name mangling issues in subclasses
        self._datastore = kw.get('__datastore')
        if kw.get('__datastore'):
            del kw['__datastore']

        # Store datastore_path (common to Watch and Tag)
        self._datastore_path = kw.get('datastore_path')
        if kw.get('datastore_path'):
            del kw['datastore_path']

        # IMPORTANT: Don't initialize __watch_was_edited yet!
        # We'll initialize it AFTER the initial update() call below
        # This prevents marking the watch as edited during initialization

        self.update({
            # Custom notification content
            # Re #110, so then if this is set to None, we know to use the default value instead
            # Requires setting to None on submit if it's the same as the default
            # Should be all None by default, so we use the system default in this case.
            'body': None,
            'browser_steps': [],
            'browser_steps_last_error_step': None,
            'conditions' : [],
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

        # Check if we're being initialized from an existing watch object
        # that has was_edited=True, so we can preserve the flag
        preserve_edited_flag = False
        if self.get('default'):
            # When creating a new watch object from an existing one (e.g., changing processor),
            # preserve the was_edited flag if it was True
            default_watch = self.get('default')
            if hasattr(default_watch, 'was_edited') and default_watch.was_edited:
                preserve_edited_flag = True
            del self['default']

        # NOW initialize the edited flag after all initial setup is complete
        # This ensures initialization doesn't trigger the edited flag
        # But preserve it if the source watch had it set to True
        self.__watch_was_edited = preserve_edited_flag

    def _mark_field_as_edited(self, key):
        """
        Helper to mark a field as edited if it's writable.

        Internal method used by __setitem__, update(), pop(), etc.
        """
        # Don't track edits during initial load or if already edited
        if not hasattr(self, '_watch_base__watch_was_edited'):
            return
        if self.__watch_was_edited:
            return  # Already marked as edited

        # Import from shared schema utilities (no circular dependency)
        from .schema_utils import get_readonly_watch_fields
        readonly_fields = get_readonly_watch_fields()

        # Additional system-managed fields not in OpenAPI spec (yet)
        # These are set by processors/workers and should not trigger edited flag
        additional_system_fields = {
            'last_check_status',  # Set by processors
            'restock',  # Set by restock processor
            'last_viewed',  # Set by mark_all_viewed endpoint
        }

        # Only mark as edited if this is a user-writable field
        if key not in readonly_fields and key not in additional_system_fields:
            self.__watch_was_edited = True

    def __setitem__(self, key, value):
        """
        Override dict.__setitem__ to track when writable watch fields are modified.

        This enables skipping reprocessing when:
        1. HTML content is unchanged (checksumFromPreviousCheckWasTheSame)
        2. AND watch configuration was not edited

        Only sets the edited flag when field is NOT in readonly_fields (from OpenAPI spec).
        """
        # Set the value first (always)
        super().__setitem__(key, value)
        # Mark as edited if writable field
        self._mark_field_as_edited(key)

    def __delitem__(self, key):
        """Override dict.__delitem__ to track deletions of writable fields."""
        super().__delitem__(key)
        self._mark_field_as_edited(key)

    def update(self, *args, **kwargs):

        if args and args[0].get('browser_steps'):
            args[0]['browser_steps'] = browser_steps_get_valid_steps(args[0].get('browser_steps'))

        """Override dict.update() to track modifications to writable fields."""
        # Call parent update first
        super().update(*args, **kwargs)

        # Mark as edited for any writable fields that were updated
        # Handle both update(dict) and update(key=value) forms
        if args:
            for key in args[0].keys():
                self._mark_field_as_edited(key)
        for key in kwargs.keys():
            self._mark_field_as_edited(key)


    def pop(self, key, *args):
        """Override dict.pop() to track removal of writable fields."""
        result = super().pop(key, *args)
        self._mark_field_as_edited(key)
        return result

    def setdefault(self, key, default=None):
        """Override dict.setdefault() to track modifications to writable fields."""
        # Only marks as edited if key didn't exist (i.e., a new value was set)
        existed = key in self
        result = super().setdefault(key, default)
        if not existed:
            self._mark_field_as_edited(key)
        return result

    @property
    def was_edited(self):
        """
        Check if watch configuration was edited since last processing.

        Returns:
            bool: True if writable fields were modified, False otherwise
        """
        return getattr(self, '_watch_base__watch_was_edited', False)

    def reset_watch_edited_flag(self):
        """
        Reset the watch edited flag after successful processing.

        Call this after processing completes to allow future content-only change detection.
        """
        self.__watch_was_edited = False

    @classmethod
    def get_property_names(cls):
        """
        Get all @property attribute names from this model class using introspection.

        This discovers computed/derived properties that are not stored in the datastore.
        These properties should be filtered out during PUT/POST requests.

        Returns:
            frozenset: Immutable set of @property attribute names from the model class
        """
        import functools

        # Create a cached version if it doesn't exist
        if not hasattr(cls, '_cached_get_property_names'):
            @functools.cache
            def _get_props():
                properties = set()
                # Use introspection to find all @property attributes
                for name in dir(cls):
                    # Skip private/magic attributes
                    if name.startswith('_'):
                        continue
                    try:
                        attr = getattr(cls, name)
                        # Check if it's a property descriptor
                        if isinstance(attr, property):
                            properties.add(name)
                    except (AttributeError, TypeError):
                        continue
                return frozenset(properties)

            cls._cached_get_property_names = _get_props

        return cls._cached_get_property_names()

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
                    # Examples: _datastore, __datastore, __app_reference, __global_settings, etc.
                    if (attr_name == '_datastore' or
                        attr_name.endswith('__datastore') or
                        attr_name.endswith('__app')):
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
                    if not (attr_name == '_datastore' or
                           attr_name.endswith('__datastore') or
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

    @property
    def data_dir(self):
        """
        The base directory for this watch/tag data (property, computed from UUID).

        Common property for both Watch and Tag objects.
        Returns path like: /datastore/{uuid}/
        """
        return os.path.join(self._datastore_path, self['uuid']) if self._datastore_path else None

    def ensure_data_dir_exists(self):
        """
        Create the data directory if it doesn't exist.

        Common method for both Watch and Tag objects.
        """
        from loguru import logger
        if not os.path.isdir(self.data_dir):
            logger.debug(f"> Creating data dir {self.data_dir}")
            os.mkdir(self.data_dir)

    def get_global_setting(self, *path):
        """
        Get a setting from the global datastore configuration.

        Args:
            *path: Path to the setting (e.g., 'application', 'history_snapshot_max_length')

        Returns:
            The setting value, or None if not found

        Example:
            maxlen = self.get_global_setting('application', 'history_snapshot_max_length')
        """
        if not self._datastore:
            return None

        try:
            value = self._datastore['settings']
            for key in path:
                value = value[key]
            return value
        except (KeyError, TypeError):
            return None

    def _get_commit_data(self):
        """
        Prepare data for commit (can be overridden by subclasses).

        Returns:
            dict: Data to serialize (filtered as needed by subclass)
        """
        import copy

        # Acquire datastore lock to prevent concurrent modifications during copy
        lock = self._datastore.lock if self._datastore and hasattr(self._datastore, 'lock') else None

        if lock:
            with lock:
                snapshot = dict(self)
        else:
            snapshot = dict(self)

        # Deep copy snapshot (slower, but done outside lock to minimize contention)
        # Subclasses can override to filter keys (e.g., Watch excludes processor_config_*)
        return {k: copy.deepcopy(v) for k, v in snapshot.items()}

    def _save_to_disk(self, data_dict, uuid):
        """
        Save data to disk (must be implemented by subclasses).

        Args:
            data_dict: Dictionary to save
            uuid: UUID for logging

        Raises:
            NotImplementedError: If subclass doesn't implement
        """
        raise NotImplementedError("Subclass must implement _save_to_disk()")

    def commit(self):
        """
        Save this watch/tag immediately to disk using atomic write.

        Common commit logic for Watch and Tag objects.
        Subclasses override _get_commit_data() and _save_to_disk() for specifics.

        Fire-and-forget: Logs errors but does not raise exceptions.
        Data remains in memory even if save fails, so next commit will retry.
        """
        from loguru import logger

        if not self.data_dir:
            entity_type = self.__class__.__name__
            logger.error(f"Cannot commit {entity_type} {self.get('uuid')} without datastore_path")
            return

        uuid = self.get('uuid')
        if not uuid:
            entity_type = self.__class__.__name__
            logger.error(f"Cannot commit {entity_type} without UUID")
            return

        # Get data from subclass (may filter keys)
        try:
            data_dict = self._get_commit_data()
        except Exception as e:
            logger.error(f"Failed to prepare commit data for {uuid}: {e}")
            return

        # Save to disk via subclass implementation
        try:
            # Determine entity type from module name (Watch.py -> watch, Tag.py -> tag)
            entity_type = _determine_entity_type(self.__class__)
            filename = f"{entity_type}.json"
            self._save_to_disk(data_dict, uuid)
            logger.debug(f"Committed {entity_type} {uuid} to {uuid}/{filename}")
        except Exception as e:
            logger.error(f"Failed to commit {uuid}: {e}")