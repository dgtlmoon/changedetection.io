import shutil

from changedetectionio.strtobool import strtobool

from changedetectionio.validate_url import is_safe_valid_url

from flask import (
    flash
)
from flask_babel import gettext

from ..blueprint.rss import RSS_CONTENT_FORMAT_DEFAULT
from ..html_tools import TRANSLATE_WHITESPACE_TABLE
from ..model import App, Watch, USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH
from copy import deepcopy, copy
from os import path, unlink
from threading import Lock
import json
import os
import re
import secrets
import sys
import threading
import time
import uuid as uuid_builder
from loguru import logger
from blinker import signal

# Try to import orjson for faster JSON serialization
try:
    import orjson

    HAS_ORJSON = True
except ImportError:
    HAS_ORJSON = False

from ..processors import get_custom_watch_obj_for_processor
from ..processors.restock_diff import Restock

# Import the base class and helpers
from .file_saving_datastore import FileSavingDataStore, load_all_watches, save_watch_atomic, save_json_atomic
from .updates import DatastoreUpdatesMixin
from .legacy_loader import has_legacy_datastore

# Because the server will run as a daemon and wont know the URL for notification links when firing off a notification
BASE_URL_NOT_SET_TEXT = '("Base URL" not set - see settings - notifications)'

dictfilt = lambda x, y: dict([(i, x[i]) for i in x if i in set(y)])


# Is there an existing library to ensure some data store (JSON etc) is in sync with CRUD methods?
# Open a github issue if you know something :)
# https://stackoverflow.com/questions/6190468/how-to-trigger-function-on-value-change
class ChangeDetectionStore(DatastoreUpdatesMixin, FileSavingDataStore):
    __version_check = True

    def __init__(self, datastore_path="/datastore", include_default_watches=True, version_tag="0.0.0"):
        # Initialize parent class
        super().__init__()

        # Should only be active for docker
        # logging.basicConfig(filename='/dev/stdout', level=logging.INFO)
        self.datastore_path = datastore_path
        self.needs_write = False
        self.start_time = time.time()
        self.stop_thread = False
        self.save_version_copy_json_db(version_tag)
        self.reload_state(datastore_path=datastore_path, include_default_watches=include_default_watches, version_tag=version_tag)

    def save_version_copy_json_db(self, version_tag):
        """
        Create version-tagged backup of changedetection.json.

        This is called on version upgrades to preserve a backup in case
        the new version has issues.
        """
        import re

        version_text = re.sub(r'\D+', '-', version_tag)
        db_path = os.path.join(self.datastore_path, "changedetection.json")
        db_path_version_backup = os.path.join(self.datastore_path, f"changedetection-{version_text}.json")

        if not os.path.isfile(db_path_version_backup) and os.path.isfile(db_path):
            from shutil import copyfile
            logger.info(f"Backing up changedetection.json due to new version to '{db_path_version_backup}'.")
            copyfile(db_path, db_path_version_backup)

    def _load_settings(self):
        """
        Load settings from storage.

        File backend implementation: reads from changedetection.json

        Returns:
            dict: Settings data loaded from storage
        """
        changedetection_json = os.path.join(self.datastore_path, "changedetection.json")

        logger.info(f"Loading settings from {changedetection_json}")

        if HAS_ORJSON:
            with open(changedetection_json, 'rb') as f:
                return orjson.loads(f.read())
        else:
            with open(changedetection_json, 'r', encoding='utf-8') as f:
                return json.load(f)

    def _apply_settings(self, settings_data):
        """
        Apply loaded settings data to internal data structure.

        Args:
            settings_data: Dictionary loaded from changedetection.json
        """
        # Apply top-level fields
        if 'app_guid' in settings_data:
            self.__data['app_guid'] = settings_data['app_guid']
        if 'build_sha' in settings_data:
            self.__data['build_sha'] = settings_data['build_sha']
        if 'version_tag' in settings_data:
            self.__data['version_tag'] = settings_data['version_tag']

        # Apply settings sections
        if 'settings' in settings_data:
            if 'headers' in settings_data['settings']:
                self.__data['settings']['headers'].update(settings_data['settings']['headers'])
            if 'requests' in settings_data['settings']:
                self.__data['settings']['requests'].update(settings_data['settings']['requests'])
            if 'application' in settings_data['settings']:
                self.__data['settings']['application'].update(settings_data['settings']['application'])

    def _rehydrate_tags(self):
        """Rehydrate tag entities from stored data."""
        for uuid, tag in self.__data['settings']['application']['tags'].items():
            self.__data['settings']['application']['tags'][uuid] = self.rehydrate_entity(
                uuid, tag, processor_override='restock_diff'
            )
            logger.info(f"Tag: {uuid} {tag['title']}")


    def _load_state(self):
        """
        Load complete datastore state from storage.

        Orchestrates loading of settings and watches using polymorphic methods.
        """
        # Load settings
        settings_data = self._load_settings()
        self._apply_settings(settings_data)

        # Load watches (polymorphic - parent class method)
        self._load_watches()

        # Rehydrate tags
        self._rehydrate_tags()

    def reload_state(self, datastore_path, include_default_watches, version_tag):
        """
        Load datastore from storage or create new one.

        Supports two scenarios:
        1. NEW format: changedetection.json exists → load and run updates if needed
        2. EMPTY: No changedetection.json → create new OR trigger migration from legacy

        Note: Legacy url-watches.json migration happens in update_26, not here.
        """
        logger.info(f"Datastore path is '{datastore_path}'")

        # Initialize data structure
        self.__data = App.model()
        self.json_store_path = os.path.join(self.datastore_path, "changedetection.json")

        # Base definition for all watchers (deepcopy part of #569)
        self.generic_definition = deepcopy(Watch.model(datastore_path=datastore_path, default={}))

        # Load build SHA if available (Docker deployments)
        if path.isfile('changedetectionio/source.txt'):
            with open('changedetectionio/source.txt') as f:
                self.__data['build_sha'] = f.read()

        # Check if datastore already exists
        changedetection_json = os.path.join(self.datastore_path, "changedetection.json")

        if os.path.exists(changedetection_json):
            # Load existing datastore (changedetection.json + watch.json files)
            logger.info("Loading existing datastore")
            try:
                self._load_state()
            except Exception as e:
                logger.critical(f"Failed to load datastore: {e}")
                raise

            # Run schema updates if needed
            self.run_updates()

        else:
            # No datastore yet - check if this is a fresh install or legacy migration
            # Generate app_guid FIRST (required for all operations)
            if "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ:
                self.__data['app_guid'] = "test-" + str(uuid_builder.uuid4())
            else:
                self.__data['app_guid'] = str(uuid_builder.uuid4())

            # Generate RSS access token
            self.__data['settings']['application']['rss_access_token'] = secrets.token_hex(16)

            # Generate API access token
            self.__data['settings']['application']['api_access_token'] = secrets.token_hex(16)

            # Check if legacy datastore exists (url-watches.json)
            if has_legacy_datastore(self.datastore_path):
                # Legacy datastore detected - trigger migration
                logger.critical(f"Legacy datastore detected at {self.datastore_path}/url-watches.json")
                logger.critical("Migration will be triggered via update_26")

                # Set schema version to 0 to trigger ALL updates including update_26
                self.__data['settings']['application']['schema_version'] = 0

                # update_26 will load the legacy data and migrate to new format
                # Data will be loaded into memory during update_26, no need to add default watches
                self.run_updates()

            else:
                # Fresh install - create new datastore
                logger.critical(f"No datastore found, creating new datastore at {self.datastore_path}")

                # Set schema version to latest (no updates needed)
                updates_available = self.get_updates_available()
                self.__data['settings']['application']['schema_version'] = updates_available.pop() if updates_available else 26

                # Add default watches if requested
                if include_default_watches:
                    self.add_watch(
                        url='https://news.ycombinator.com/',
                        tag='Tech news',
                        extras={'fetch_backend': 'html_requests'}
                    )
                    self.add_watch(
                        url='https://changedetection.io/CHANGELOG.txt',
                        tag='changedetection.io',
                        extras={'fetch_backend': 'html_requests'}
                    )

                # Create changedetection.json immediately
                try:
                    self._save_settings()
                    logger.info("Created changedetection.json for new datastore")
                except Exception as e:
                    logger.error(f"Failed to create initial changedetection.json: {e}")

        # Set version tag
        self.__data['version_tag'] = version_tag

        # Validate proxies.json if it exists
        _ = self.proxy_list  # Just to test parsing

        # Ensure app_guid exists (for datastores loaded from existing files)
        if 'app_guid' not in self.__data:
            if "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ:
                self.__data['app_guid'] = "test-" + str(uuid_builder.uuid4())
            else:
                self.__data['app_guid'] = str(uuid_builder.uuid4())
            self.mark_settings_dirty()

        # Ensure RSS access token exists
        if not self.__data['settings']['application'].get('rss_access_token'):
            secret = secrets.token_hex(16)
            self.__data['settings']['application']['rss_access_token'] = secret
            self.mark_settings_dirty()

        # Ensure API access token exists
        if not self.__data['settings']['application'].get('api_access_token'):
            secret = secrets.token_hex(16)
            self.__data['settings']['application']['api_access_token'] = secret
            self.mark_settings_dirty()

        # Handle password reset lockfile
        password_reset_lockfile = os.path.join(self.datastore_path, "removepassword.lock")
        if path.isfile(password_reset_lockfile):
            self.remove_password()
            unlink(password_reset_lockfile)

        # Start the background save thread
        self.start_save_thread()

    def rehydrate_entity(self, uuid, entity, processor_override=None):
        """Set the dict back to the dict Watch object"""
        entity['uuid'] = uuid

        if processor_override:
            watch_class = get_custom_watch_obj_for_processor(processor_override)
            entity['processor'] = processor_override
        else:
            watch_class = get_custom_watch_obj_for_processor(entity.get('processor'))

        if entity.get('uuid') != 'text_json_diff':
            logger.trace(f"Loading Watch object '{watch_class.__module__}.{watch_class.__name__}' for UUID {uuid}")

        entity = watch_class(datastore_path=self.datastore_path, default=entity)
        return entity

    # ============================================================================
    # FileSavingDataStore Abstract Method Implementations
    # ============================================================================

    def _watch_exists(self, uuid):
        """Check if watch exists in datastore."""
        return uuid in self.__data['watching']

    def _get_watch_dict(self, uuid):
        """Get watch as dictionary."""
        return dict(self.__data['watching'][uuid])

    def _build_settings_data(self):
        """
        Build settings data structure for saving.

        Returns:
            dict: Settings data ready for serialization
        """
        return {
            'note': 'Settings file - watches are stored in individual {uuid}/watch.json files',
            'app_guid': self.__data['app_guid'],
            'settings': self.__data['settings'],
            'build_sha': self.__data.get('build_sha'),
            'version_tag': self.__data.get('version_tag')
        }

    def _save_settings(self):
        """
        Save settings to storage.

        File backend implementation: saves to changedetection.json
        Implementation of abstract method from FileSavingDataStore.
        Uses the generic save_json_atomic helper.

        Raises:
            OSError: If disk is full or other I/O error
        """
        settings_data = self._build_settings_data()
        changedetection_json = os.path.join(self.datastore_path, "changedetection.json")
        save_json_atomic(changedetection_json, settings_data, label="settings", max_size_mb=10)

    def _load_watches(self):
        """
        Load all watches from storage.

        File backend implementation: reads individual watch.json files
        Implementation of abstract method from FileSavingDataStore.
        Delegates to helper function and stores results in internal data structure.
        """
        watching, watch_hashes = load_all_watches(
            self.datastore_path,
            self.rehydrate_entity,
            self._compute_hash
        )

        # Store loaded data
        self.__data['watching'] = watching
        self._watch_hashes = watch_hashes

    def _delete_watch(self, uuid):
        """
        Delete a watch from storage.

        File backend implementation: deletes entire {uuid}/ directory recursively.
        Implementation of abstract method from FileSavingDataStore.

        Args:
            uuid: Watch UUID to delete
        """
        watch_dir = os.path.join(self.datastore_path, uuid)
        if os.path.exists(watch_dir):
            shutil.rmtree(watch_dir)
            logger.info(f"Deleted watch directory: {watch_dir}")

    # ============================================================================
    # Watch Management Methods
    # ============================================================================

    def set_last_viewed(self, uuid, timestamp):
        logger.debug(f"Setting watch UUID: {uuid} last viewed to {int(timestamp)}")
        self.data['watching'][uuid].update({'last_viewed': int(timestamp)})
        self.mark_watch_dirty(uuid)

        watch_check_update = signal('watch_check_update')
        if watch_check_update:
            watch_check_update.send(watch_uuid=uuid)

    def remove_password(self):
        self.__data['settings']['application']['password'] = False
        self.mark_settings_dirty()

    def update_watch(self, uuid, update_obj):

        # It's possible that the watch could be deleted before update
        if not self.__data['watching'].get(uuid):
            return

        with self.lock:

            # In python 3.9 we have the |= dict operator, but that still will lose data on nested structures...
            for dict_key, d in self.generic_definition.items():
                if isinstance(d, dict):
                    if update_obj is not None and dict_key in update_obj:
                        self.__data['watching'][uuid][dict_key].update(update_obj[dict_key])
                        del (update_obj[dict_key])

            self.__data['watching'][uuid].update(update_obj)

        self.mark_watch_dirty(uuid)

    @property
    def threshold_seconds(self):
        seconds = 0
        for m, n in Watch.mtable.items():
            x = self.__data['settings']['requests']['time_between_check'].get(m)
            if x:
                seconds += x * n
        return seconds

    @property
    def unread_changes_count(self):
        unread_changes_count = 0
        for uuid, watch in self.__data['watching'].items():
            if watch.history_n >= 2 and watch.viewed == False:
                unread_changes_count += 1

        return unread_changes_count

    @property
    def data(self):
        # Re #152, Return env base_url if not overriden
        # Re #148 - Some people have just {{ base_url }} in the body or title, but this may break some notification services
        #           like 'Join', so it's always best to atleast set something obvious so that they are not broken.

        active_base_url = BASE_URL_NOT_SET_TEXT
        if self.__data['settings']['application'].get('base_url'):
            active_base_url = self.__data['settings']['application'].get('base_url')
        elif os.getenv('BASE_URL'):
            active_base_url = os.getenv('BASE_URL')

        # I looked at various ways todo the following, but in the end just copying the dict seemed simplest/most reliable
        # even given the memory tradeoff - if you know a better way.. maybe return d|self.__data.. or something
        d = self.__data
        d['settings']['application']['active_base_url'] = active_base_url.strip('" ')
        return d

    # Delete a single watch by UUID
    def delete(self, uuid):
        """
        Delete a watch by UUID.

        Uses abstracted storage method for backend-agnostic deletion.
        Supports 'all' to delete all watches (mainly for testing).

        Args:
            uuid: Watch UUID to delete, or 'all' to delete all watches
        """
        with self.lock:
            if uuid == 'all':
                # Delete all watches - capture UUIDs first before modifying dict
                all_uuids = list(self.__data['watching'].keys())

                for watch_uuid in all_uuids:
                    # Delete from storage using polymorphic method
                    try:
                        self._delete_watch(watch_uuid)
                    except Exception as e:
                        logger.error(f"Failed to delete watch {watch_uuid} from storage: {e}")

                    # Clean up tracking data
                    self._watch_hashes.pop(watch_uuid, None)
                    self._dirty_watches.discard(watch_uuid)

                    # Send delete signal
                    watch_delete_signal = signal('watch_deleted')
                    if watch_delete_signal:
                        watch_delete_signal.send(watch_uuid=watch_uuid)

                # Clear the dict
                self.__data['watching'] = {}

                # Mainly used for testing to allow all items to flush before running next test
                time.sleep(1)

            else:
                # Delete single watch from storage using polymorphic method
                try:
                    self._delete_watch(uuid)
                except Exception as e:
                    logger.error(f"Failed to delete watch {uuid} from storage: {e}")

                # Remove from watching dict
                del self.data['watching'][uuid]

                # Clean up tracking data
                self._watch_hashes.pop(uuid, None)
                self._dirty_watches.discard(uuid)

                # Send delete signal
                watch_delete_signal = signal('watch_deleted')
                if watch_delete_signal:
                    watch_delete_signal.send(watch_uuid=uuid)

        self.needs_write_urgent = True

    # Clone a watch by UUID
    def clone(self, uuid):
        url = self.data['watching'][uuid].get('url')
        extras = deepcopy(self.data['watching'][uuid])
        new_uuid = self.add_watch(url=url, extras=extras)
        watch = self.data['watching'][new_uuid]
        return new_uuid

    def url_exists(self, url):

        # Probably their should be dict...
        for watch in self.data['watching'].values():
            if watch['url'].lower() == url.lower():
                return True

        return False

    # Remove a watchs data but keep the entry (URL etc)
    def clear_watch_history(self, uuid):
        self.__data['watching'][uuid].clear_watch()
        self.needs_write_urgent = True

    def add_watch(self, url, tag='', extras=None, tag_uuids=None, save_immediately=True):
        import requests

        if extras is None:
            extras = {}

        # Incase these are copied across, assume it's a reference and deepcopy()
        apply_extras = deepcopy(extras)
        apply_extras['tags'] = [] if not apply_extras.get('tags') else apply_extras.get('tags')

        # Was it a share link? try to fetch the data
        if (url.startswith("https://changedetection.io/share/")):
            try:
                r = requests.request(method="GET",
                                     url=url,
                                     # So we know to return the JSON instead of the human-friendly "help" page
                                     headers={'App-Guid': self.__data['app_guid']},
                                     timeout=5.0)  # 5 second timeout to prevent blocking
                res = r.json()

                # List of permissible attributes we accept from the wild internet
                for k in [
                    'body',
                    'browser_steps',
                    'css_filter',
                    'extract_text',
                    'headers',
                    'ignore_text',
                    'include_filters',
                    'method',
                    'paused',
                    'previous_md5',
                    'processor',
                    'subtractive_selectors',
                    'tag',
                    'tags',
                    'text_should_not_be_present',
                    'title',
                    'trigger_text',
                    'url',
                    'use_page_title_in_list',
                    'webdriver_js_execute_code',
                ]:
                    if res.get(k):
                        if k != 'css_filter':
                            apply_extras[k] = res[k]
                        else:
                            # We renamed the field and made it a list
                            apply_extras['include_filters'] = [res['css_filter']]

            except Exception as e:
                logger.error(f"Error fetching metadata for shared watch link {url} {str(e)}")
                flash(gettext("Error fetching metadata for {}").format(url), 'error')
                return False

        if not is_safe_valid_url(url):
            flash(gettext('Watch protocol is not permitted or invalid URL format'), 'error')

            return None

        if tag and type(tag) == str:
            # Then it's probably a string of the actual tag by name, split and add it
            for t in tag.split(','):
                # for each stripped tag, add tag as UUID
                for a_t in t.split(','):
                    tag_uuid = self.add_tag(a_t)
                    apply_extras['tags'].append(tag_uuid)

        # Or if UUIDs given directly
        if tag_uuids:
            for t in tag_uuids:
                apply_extras['tags'] = list(set(apply_extras['tags'] + [t.strip()]))

        # Make any uuids unique
        if apply_extras.get('tags'):
            apply_extras['tags'] = list(set(apply_extras.get('tags')))

        # If the processor also has its own Watch implementation
        watch_class = get_custom_watch_obj_for_processor(apply_extras.get('processor'))
        new_watch = watch_class(datastore_path=self.datastore_path, url=url)

        new_uuid = new_watch.get('uuid')

        logger.debug(f"Adding URL '{url}' - {new_uuid}")

        for k in ['uuid', 'history', 'last_checked', 'last_changed', 'newest_history_key', 'previous_md5', 'viewed']:
            if k in apply_extras:
                del apply_extras[k]

        if not apply_extras.get('date_created'):
            apply_extras['date_created'] = int(time.time())

        new_watch.update(apply_extras)
        new_watch.ensure_data_dir_exists()
        self.__data['watching'][new_uuid] = new_watch

        if save_immediately:
            # Save immediately using polymorphic method
            try:
                self.save_watch(new_uuid, force=True)
                logger.debug(f"Saved new watch {new_uuid}")
            except Exception as e:
                logger.error(f"Failed to save new watch {new_uuid}: {e}")
                # Mark dirty for retry
                self.mark_watch_dirty(new_uuid)
        else:
            self.mark_watch_dirty(new_uuid)

        logger.debug(f"Added '{url}'")

        return new_uuid

    def _watch_resource_exists(self, watch_uuid, resource_name):
        """
        Check if a watch-related resource exists.

        File backend implementation: checks if file exists in watch directory.

        Args:
            watch_uuid: Watch UUID
            resource_name: Name of resource (e.g., "last-screenshot.png")

        Returns:
            bool: True if resource exists
        """
        resource_path = os.path.join(self.datastore_path, watch_uuid, resource_name)
        return path.isfile(resource_path)

    def visualselector_data_is_ready(self, watch_uuid):
        """
        Check if visual selector data (screenshot + elements) is ready.

        Returns:
            bool: True if both screenshot and elements data exist
        """
        has_screenshot = self._watch_resource_exists(watch_uuid, "last-screenshot.png")
        has_elements = self._watch_resource_exists(watch_uuid, "elements.deflate")
        return has_screenshot and has_elements

    # Old sync_to_json and save_datastore methods removed - now handled by FileSavingDataStore parent class

    # Go through the datastore path and remove any snapshots that are not mentioned in the index
    # This usually is not used, but can be handy.
    def remove_unused_snapshots(self):
        logger.info("Removing snapshots from datastore that are not in the index..")

        index = []
        for uuid in self.data['watching']:
            for id in self.data['watching'][uuid].history:
                index.append(self.data['watching'][uuid].history[str(id)])

        import pathlib

        # Only in the sub-directories
        for uuid in self.data['watching']:
            for item in pathlib.Path(self.datastore_path).rglob(uuid + "/*.txt"):
                if not str(item) in index:
                    logger.info(f"Removing {item}")
                    unlink(item)

    @property
    def proxy_list(self):
        proxy_list = {}
        proxy_list_file = os.path.join(self.datastore_path, 'proxies.json')

        # Load from external config file
        if path.isfile(proxy_list_file):
            if HAS_ORJSON:
                # orjson.loads() expects UTF-8 encoded bytes #3611
                with open(os.path.join(self.datastore_path, "proxies.json"), 'rb') as f:
                    proxy_list = orjson.loads(f.read())
            else:
                with open(os.path.join(self.datastore_path, "proxies.json"), encoding='utf-8') as f:
                    proxy_list = json.load(f)

        # Mapping from UI config if available
        extras = self.data['settings']['requests'].get('extra_proxies')
        if extras:
            i = 0
            for proxy in extras:
                i += 0
                if proxy.get('proxy_name') and proxy.get('proxy_url'):
                    k = "ui-" + str(i) + proxy.get('proxy_name')
                    proxy_list[k] = {'label': proxy.get('proxy_name'), 'url': proxy.get('proxy_url')}

        if proxy_list and strtobool(os.getenv('ENABLE_NO_PROXY_OPTION', 'True')):
            proxy_list["no-proxy"] = {'label': "No proxy", 'url': ''}

        return proxy_list if len(proxy_list) else None

    def get_preferred_proxy_for_watch(self, uuid):
        """
        Returns the preferred proxy by ID key
        :param uuid: UUID
        :return: proxy "key" id
        """

        if self.proxy_list is None:
            return None

        # If it's a valid one
        watch = self.data['watching'].get(uuid)

        if strtobool(os.getenv('ENABLE_NO_PROXY_OPTION', 'True')) and watch.get('proxy') == "no-proxy":
            return None

        if watch.get('proxy') and watch.get('proxy') in list(self.proxy_list.keys()):
            return watch.get('proxy')

        # not valid (including None), try the system one
        else:
            system_proxy_id = self.data['settings']['requests'].get('proxy')
            # Is not None and exists
            if self.proxy_list.get(system_proxy_id):
                return system_proxy_id

        # Fallback - Did not resolve anything, or doesnt exist, use the first available
        if system_proxy_id is None or not self.proxy_list.get(system_proxy_id):
            first_default = list(self.proxy_list)[0]
            return first_default

        return None

    @property
    def has_extra_headers_file(self):
        filepath = os.path.join(self.datastore_path, 'headers.txt')
        return os.path.isfile(filepath)

    def get_all_base_headers(self):
        headers = {}
        # Global app settings
        headers.update(self.data['settings'].get('headers', {}))

        return headers

    def get_all_headers_in_textfile_for_watch(self, uuid):
        from ..model.App import parse_headers_from_text_file
        headers = {}

        # Global in /datastore/headers.txt
        filepath = os.path.join(self.datastore_path, 'headers.txt')
        try:
            if os.path.isfile(filepath):
                headers.update(parse_headers_from_text_file(filepath))
        except Exception as e:
            logger.error(f"ERROR reading headers.txt at {filepath} {str(e)}")

        watch = self.data['watching'].get(uuid)
        if watch:

            # In /datastore/xyz-xyz/headers.txt
            filepath = os.path.join(watch.watch_data_dir, 'headers.txt')
            try:
                if os.path.isfile(filepath):
                    headers.update(parse_headers_from_text_file(filepath))
            except Exception as e:
                logger.error(f"ERROR reading headers.txt at {filepath} {str(e)}")

            # In /datastore/tag-name.txt
            tags = self.get_all_tags_for_watch(uuid=uuid)
            for tag_uuid, tag in tags.items():
                fname = "headers-" + re.sub(r'[\W_]', '', tag.get('title')).lower().strip() + ".txt"
                filepath = os.path.join(self.datastore_path, fname)
                try:
                    if os.path.isfile(filepath):
                        headers.update(parse_headers_from_text_file(filepath))
                except Exception as e:
                    logger.error(f"ERROR reading headers.txt at {filepath} {str(e)}")

        return headers

    def get_tag_overrides_for_watch(self, uuid, attr):
        tags = self.get_all_tags_for_watch(uuid=uuid)
        ret = []

        if tags:
            for tag_uuid, tag in tags.items():
                if attr in tag and tag[attr]:
                    ret = [*ret, *tag[attr]]

        return ret

    def add_tag(self, title):
        # If name exists, return that
        n = title.strip().lower()
        logger.debug(f">>> Adding new tag - '{n}'")
        if not n:
            return False

        for uuid, tag in self.__data['settings']['application'].get('tags', {}).items():
            if n == tag.get('title', '').lower().strip():
                logger.warning(f"Tag '{title}' already exists, skipping creation.")
                return uuid

        # Eventually almost everything todo with a watch will apply as a Tag
        # So we use the same model as a Watch
        with self.lock:
            from ..model import Tag
            new_tag = Tag.model(datastore_path=self.datastore_path, default={
                'title': title.strip(),
                'date_created': int(time.time())
            })

            new_uuid = new_tag.get('uuid')

            self.__data['settings']['application']['tags'][new_uuid] = new_tag

        self.mark_settings_dirty()
        return new_uuid

    def get_all_tags_for_watch(self, uuid):
        """This should be in Watch model but Watch doesn't have access to datastore, not sure how to solve that yet"""
        watch = self.data['watching'].get(uuid)

        # Should return a dict of full tag info linked by UUID
        if watch:
            return dictfilt(self.__data['settings']['application']['tags'], watch.get('tags', []))

        return {}

    @property
    def extra_browsers(self):
        res = []
        p = list(filter(
            lambda s: (s.get('browser_name') and s.get('browser_connection_url')),
            self.__data['settings']['requests'].get('extra_browsers', [])))
        if p:
            for i in p:
                res.append(("extra_browser_" + i['browser_name'], i['browser_name']))

        return res

    def tag_exists_by_name(self, tag_name):
        # Check if any tag dictionary has a 'title' attribute matching the provided tag_name
        tags = self.__data['settings']['application']['tags'].values()
        return next((v for v in tags if v.get('title', '').lower() == tag_name.lower()),
                    None)

    def any_watches_have_processor_by_name(self, processor_name):
        for watch in self.data['watching'].values():
            if watch.get('processor') == processor_name:
                return True
        return False

    def search_watches_for_url(self, query, tag_limit=None, partial=False):
        """Search watches by URL, title, or error messages

        Args:
            query (str): Search term to match against watch URLs, titles, and error messages
            tag_limit (str, optional): Optional tag name to limit search results
            partial: (bool, optional): sub-string matching

        Returns:
            list: List of UUIDs of watches that match the search criteria
        """
        matching_uuids = []
        query = query.lower().strip()
        tag = self.tag_exists_by_name(tag_limit) if tag_limit else False

        for uuid, watch in self.data['watching'].items():
            # Filter by tag if requested
            if tag_limit:
                if not tag.get('uuid') in watch.get('tags', []):
                    continue

            # Search in URL, title, or error messages
            if partial:
                if ((watch.get('title') and query in watch.get('title').lower()) or
                        query in watch.get('url', '').lower() or
                        (watch.get('last_error') and query in watch.get('last_error').lower())):
                    matching_uuids.append(uuid)
            else:
                if ((watch.get('title') and query == watch.get('title').lower()) or
                        query == watch.get('url', '').lower() or
                        (watch.get('last_error') and query == watch.get('last_error').lower())):
                    matching_uuids.append(uuid)

        return matching_uuids

    def get_unique_notification_tokens_available(self):
        # Ask each type of watch if they have any extra notification token to add to the validation
        extra_notification_tokens = {}
        watch_processors_checked = set()

        for watch_uuid, watch in self.__data['watching'].items():
            processor = watch.get('processor')
            if processor not in watch_processors_checked:
                extra_notification_tokens.update(watch.extra_notification_token_values())
                watch_processors_checked.add(processor)

        return extra_notification_tokens

    def get_unique_notification_token_placeholders_available(self):
        # The actual description of the tokens, could be combined with get_unique_notification_tokens_available instead of doing this twice
        extra_notification_tokens = []
        watch_processors_checked = set()

        for watch_uuid, watch in self.__data['watching'].items():
            processor = watch.get('processor')
            if processor not in watch_processors_checked:
                extra_notification_tokens += watch.extra_notification_token_placeholder_info()
                watch_processors_checked.add(processor)

        return extra_notification_tokens

    def add_notification_url(self, notification_url):

        logger.debug(f">>> Adding new notification_url - '{notification_url}'")

        notification_urls = self.data['settings']['application'].get('notification_urls', [])

        if notification_url in notification_urls:
            return notification_url

        with self.lock:
            notification_urls = self.__data['settings']['application'].get('notification_urls', [])

            if notification_url in notification_urls:
                return notification_url

            # Append and update the datastore
            notification_urls.append(notification_url)
            self.__data['settings']['application']['notification_urls'] = notification_urls

        self.mark_settings_dirty()
        return notification_url

    # Schema update methods moved to store/updates.py (DatastoreUpdatesMixin)
    # This includes: get_updates_available(), run_updates(), and update_1() through update_26()
