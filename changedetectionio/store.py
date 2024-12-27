from changedetectionio.strtobool import strtobool

from flask import (
    flash
)

from .html_tools import TRANSLATE_WHITESPACE_TABLE
from . model import App, Watch
from copy import deepcopy, copy
from os import path, unlink
from threading import Lock
import json
import os
import re
import secrets
import threading
import time
import uuid as uuid_builder
from loguru import logger

from .processors import get_custom_watch_obj_for_processor
from .processors.restock_diff import Restock

# Because the server will run as a daemon and wont know the URL for notification links when firing off a notification
BASE_URL_NOT_SET_TEXT = '("Base URL" not set - see settings - notifications)'

dictfilt = lambda x, y: dict([ (i,x[i]) for i in x if i in set(y) ])

# Is there an existing library to ensure some data store (JSON etc) is in sync with CRUD methods?
# Open a github issue if you know something :)
# https://stackoverflow.com/questions/6190468/how-to-trigger-function-on-value-change
class ChangeDetectionStore:
    lock = Lock()
    # For general updates/writes that can wait a few seconds
    needs_write = False

    # For when we edit, we should write to disk
    needs_write_urgent = False

    __version_check = True

    def __init__(self, datastore_path="/datastore", include_default_watches=True, version_tag="0.0.0"):
        # Should only be active for docker
        # logging.basicConfig(filename='/dev/stdout', level=logging.INFO)
        self.__data = App.model()
        self.datastore_path = datastore_path
        self.json_store_path = "{}/url-watches.json".format(self.datastore_path)
        logger.info(f"Datastore path is '{self.json_store_path}'")
        self.needs_write = False
        self.start_time = time.time()
        self.stop_thread = False
        # Base definition for all watchers
        # deepcopy part of #569 - not sure why its needed exactly
        self.generic_definition = deepcopy(Watch.model(datastore_path = datastore_path, default={}))

        if path.isfile('changedetectionio/source.txt'):
            with open('changedetectionio/source.txt') as f:
                # Should be set in Dockerfile to look for /source.txt , this will give us the git commit #
                # So when someone gives us a backup file to examine, we know exactly what code they were running.
                self.__data['build_sha'] = f.read()

        try:
            # @todo retest with ", encoding='utf-8'"
            with open(self.json_store_path) as json_file:
                from_disk = json.load(json_file)

                # @todo isnt there a way todo this dict.update recursively?
                # Problem here is if the one on the disk is missing a sub-struct, it wont be present anymore.
                if 'watching' in from_disk:
                    self.__data['watching'].update(from_disk['watching'])

                if 'app_guid' in from_disk:
                    self.__data['app_guid'] = from_disk['app_guid']

                if 'settings' in from_disk:
                    if 'headers' in from_disk['settings']:
                        self.__data['settings']['headers'].update(from_disk['settings']['headers'])

                    if 'requests' in from_disk['settings']:
                        self.__data['settings']['requests'].update(from_disk['settings']['requests'])

                    if 'application' in from_disk['settings']:
                        self.__data['settings']['application'].update(from_disk['settings']['application'])

                # Convert each existing watch back to the Watch.model object
                for uuid, watch in self.__data['watching'].items():
                    self.__data['watching'][uuid] = self.rehydrate_entity(uuid, watch)
                    logger.info(f"Watching: {uuid} {watch['url']}")

                # And for Tags also, should be Restock type because it has extra settings
                for uuid, tag in self.__data['settings']['application']['tags'].items():
                    self.__data['settings']['application']['tags'][uuid] = self.rehydrate_entity(uuid, tag, processor_override='restock_diff')
                    logger.info(f"Tag: {uuid} {tag['title']}")

        # First time ran, Create the datastore.
        except (FileNotFoundError):
            if include_default_watches:
                logger.critical(f"No JSON DB found at {self.json_store_path}, creating JSON store at {self.datastore_path}")
                self.add_watch(url='https://news.ycombinator.com/',
                               tag='Tech news',
                               extras={'fetch_backend': 'html_requests'})

                self.add_watch(url='https://changedetection.io/CHANGELOG.txt',
                               tag='changedetection.io',
                               extras={'fetch_backend': 'html_requests'})

            updates_available = self.get_updates_available()
            self.__data['settings']['application']['schema_version'] = updates_available.pop()

        else:
            # Bump the update version by running updates
            self.run_updates()

        self.__data['version_tag'] = version_tag

        # Just to test that proxies.json if it exists, doesnt throw a parsing error on startup
        test_list = self.proxy_list

        # Helper to remove password protection
        password_reset_lockfile = "{}/removepassword.lock".format(self.datastore_path)
        if path.isfile(password_reset_lockfile):
            self.__data['settings']['application']['password'] = False
            unlink(password_reset_lockfile)

        if not 'app_guid' in self.__data:
            import os
            import sys
            if "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ:
                self.__data['app_guid'] = "test-" + str(uuid_builder.uuid4())
            else:
                self.__data['app_guid'] = str(uuid_builder.uuid4())

        # Generate the URL access token for RSS feeds
        if not self.__data['settings']['application'].get('rss_access_token'):
            secret = secrets.token_hex(16)
            self.__data['settings']['application']['rss_access_token'] = secret

        # Generate the API access token
        if not self.__data['settings']['application'].get('api_access_token'):
            secret = secrets.token_hex(16)
            self.__data['settings']['application']['api_access_token'] = secret

        self.needs_write = True

        # Finally start the thread that will manage periodic data saves to JSON
        save_data_thread = threading.Thread(target=self.save_datastore).start()

    def rehydrate_entity(self, uuid, entity, processor_override=None):
        """Set the dict back to the dict Watch object"""
        entity['uuid'] = uuid

        if processor_override:
            watch_class = get_custom_watch_obj_for_processor(processor_override)
            entity['processor']=processor_override
        else:
            watch_class = get_custom_watch_obj_for_processor(entity.get('processor'))

        if entity.get('uuid') != 'text_json_diff':
            logger.trace(f"Loading Watch object '{watch_class.__module__}.{watch_class.__name__}' for UUID {uuid}")

        entity = watch_class(datastore_path=self.datastore_path, default=entity)
        return entity

    def set_last_viewed(self, uuid, timestamp):
        logger.debug(f"Setting watch UUID: {uuid} last viewed to {int(timestamp)}")
        self.data['watching'][uuid].update({'last_viewed': int(timestamp)})
        self.needs_write = True

    def remove_password(self):
        self.__data['settings']['application']['password'] = False
        self.needs_write = True

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
        self.needs_write = True

    @property
    def threshold_seconds(self):
        seconds = 0
        for m, n in Watch.mtable.items():
            x = self.__data['settings']['requests']['time_between_check'].get(m)
            if x:
                seconds += x * n
        return seconds

    @property
    def has_unviewed(self):
        if not self.__data.get('watching'):
            return None

        for uuid, watch in self.__data['watching'].items():
            if watch.history_n >= 2 and watch.viewed == False:
                return True
        return False

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
        import pathlib
        import shutil

        with self.lock:
            if uuid == 'all':
                self.__data['watching'] = {}

                # GitHub #30 also delete history records
                for uuid in self.data['watching']:
                    path = pathlib.Path(os.path.join(self.datastore_path, uuid))
                    if os.path.exists(path):
                        shutil.rmtree(path)

            else:
                path = pathlib.Path(os.path.join(self.datastore_path, uuid))
                if os.path.exists(path):
                    shutil.rmtree(path)
                del self.data['watching'][uuid]

        self.needs_write_urgent = True

    # Clone a watch by UUID
    def clone(self, uuid):
        url = self.data['watching'][uuid].get('url')
        extras = self.data['watching'][uuid]
        new_uuid = self.add_watch(url=url, extras=extras)
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

    def add_watch(self, url, tag='', extras=None, tag_uuids=None, write_to_disk_now=True):
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
                                     headers={'App-Guid': self.__data['app_guid']})
                res = r.json()

                # List of permissible attributes we accept from the wild internet
                for k in [
                    'body',
                    'browser_steps',
                    'css_filter',
                    'extract_text',
                    'extract_title_as_title',
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
                flash("Error fetching metadata for {}".format(url), 'error')
                return False
        from .model.Watch import is_safe_url
        if not is_safe_url(url):
            flash('Watch protocol is not permitted by SAFE_PROTOCOL_REGEX', 'error')
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


        if write_to_disk_now:
            self.sync_to_json()

        logger.debug(f"Added '{url}'")

        return new_uuid

    def visualselector_data_is_ready(self, watch_uuid):
        output_path = "{}/{}".format(self.datastore_path, watch_uuid)
        screenshot_filename = "{}/last-screenshot.png".format(output_path)
        elements_index_filename = "{}/elements.deflate".format(output_path)
        if path.isfile(screenshot_filename) and  path.isfile(elements_index_filename) :
            return True

        return False

    def sync_to_json(self):
        logger.info("Saving JSON..")
        try:
            data = deepcopy(self.__data)
        except RuntimeError as e:
            # Try again in 15 seconds
            time.sleep(15)
            logger.error(f"! Data changed when writing to JSON, trying again.. {str(e)}")
            self.sync_to_json()
            return
        else:

            try:
                # Re #286  - First write to a temp file, then confirm it looks OK and rename it
                # This is a fairly basic strategy to deal with the case that the file is corrupted,
                # system was out of memory, out of RAM etc
                with open(self.json_store_path+".tmp", 'w') as json_file:
                    json.dump(data, json_file, indent=4)
                os.replace(self.json_store_path+".tmp", self.json_store_path)
            except Exception as e:
                logger.error(f"Error writing JSON!! (Main JSON file save was skipped) : {str(e)}")

            self.needs_write = False
            self.needs_write_urgent = False

    # Thread runner, this helps with thread/write issues when there are many operations that want to update the JSON
    # by just running periodically in one thread, according to python, dict updates are threadsafe.
    def save_datastore(self):

        while True:
            if self.stop_thread:
                # Suppressing "Logging error in Loguru Handler #0" during CICD.
                # Not a meaningful difference for a real use-case just for CICD.
                # the side effect is a "Shutting down datastore thread" message
                # at the end of each test.
                # But still more looking better.
                import sys
                logger.remove()
                logger.add(sys.stderr)

                logger.critical("Shutting down datastore thread")
                return

            if self.needs_write or self.needs_write_urgent:
                self.sync_to_json()

            # Once per minute is enough, more and it can cause high CPU usage
            # better here is to use something like self.app.config.exit.wait(1), but we cant get to 'app' from here
            for i in range(120):
                time.sleep(0.5)
                if self.stop_thread or self.needs_write_urgent:
                    break

    # Go through the datastore path and remove any snapshots that are not mentioned in the index
    # This usually is not used, but can be handy.
    def remove_unused_snapshots(self):
        logger.info("Removing snapshots from datastore that are not in the index..")

        index=[]
        for uuid in self.data['watching']:
            for id in self.data['watching'][uuid].history:
                index.append(self.data['watching'][uuid].history[str(id)])

        import pathlib

        # Only in the sub-directories
        for uuid in self.data['watching']:
            for item in pathlib.Path(self.datastore_path).rglob(uuid+"/*.txt"):
                if not str(item) in index:
                    logger.info(f"Removing {item}")
                    unlink(item)

    @property
    def proxy_list(self):
        proxy_list = {}
        proxy_list_file = os.path.join(self.datastore_path, 'proxies.json')

        # Load from external config file
        if path.isfile(proxy_list_file):
            with open("{}/proxies.json".format(self.datastore_path)) as f:
                proxy_list = json.load(f)

        # Mapping from UI config if available
        extras = self.data['settings']['requests'].get('extra_proxies')
        if extras:
            i=0
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
        from .model.App import parse_headers_from_text_file
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
                fname = "headers-"+re.sub(r'[\W_]', '', tag.get('title')).lower().strip() + ".txt"
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
                    ret=[*ret, *tag[attr]]

        return ret

    def add_tag(self, name):
        # If name exists, return that
        n = name.strip().lower()
        logger.debug(f">>> Adding new tag - '{n}'")
        if not n:
            return False

        for uuid, tag in self.__data['settings']['application'].get('tags', {}).items():
            if n == tag.get('title', '').lower().strip():
                logger.warning(f"Tag '{name}' already exists, skipping creation.")
                return uuid

        # Eventually almost everything todo with a watch will apply as a Tag
        # So we use the same model as a Watch
        with self.lock:
            from .model import Tag
            new_tag = Tag.model(datastore_path=self.datastore_path, default={
                'title': name.strip(),
                'date_created': int(time.time())
            })

            new_uuid = new_tag.get('uuid')

            self.__data['settings']['application']['tags'][new_uuid] = new_tag

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
                res.append(("extra_browser_"+i['browser_name'], i['browser_name']))

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
                extra_notification_tokens+=watch.extra_notification_token_placeholder_info()
                watch_processors_checked.add(processor)

        return extra_notification_tokens


    def get_updates_available(self):
        import inspect
        updates_available = []
        for i, o in inspect.getmembers(self, predicate=inspect.ismethod):
            m = re.search(r'update_(\d+)$', i)
            if m:
                updates_available.append(int(m.group(1)))
        updates_available.sort()

        return updates_available

    # Run all updates
    # IMPORTANT - Each update could be run even when they have a new install and the schema is correct
    #             So therefor - each `update_n` should be very careful about checking if it needs to actually run
    #             Probably we should bump the current update schema version with each tag release version?
    def run_updates(self):
        import shutil
        updates_available = self.get_updates_available()
        for update_n in updates_available:
            if update_n > self.__data['settings']['application']['schema_version']:
                logger.critical(f"Applying update_{update_n}")
                # Wont exist on fresh installs
                if os.path.exists(self.json_store_path):
                    shutil.copyfile(self.json_store_path, self.datastore_path+"/url-watches-before-{}.json".format(update_n))

                try:
                    update_method = getattr(self, "update_{}".format(update_n))()
                except Exception as e:
                    logger.error(f"Error while trying update_{update_n}")
                    logger.error(e)
                    # Don't run any more updates
                    return
                else:
                    # Bump the version, important
                    self.__data['settings']['application']['schema_version'] = update_n

    # Convert minutes to seconds on settings and each watch
    def update_1(self):
        if self.data['settings']['requests'].get('minutes_between_check'):
            self.data['settings']['requests']['time_between_check']['minutes'] = self.data['settings']['requests']['minutes_between_check']
            # Remove the default 'hours' that is set from the model
            self.data['settings']['requests']['time_between_check']['hours'] = None

        for uuid, watch in self.data['watching'].items():
            if 'minutes_between_check' in watch:
                # Only upgrade individual watch time if it was set
                if watch.get('minutes_between_check', False):
                    self.data['watching'][uuid]['time_between_check']['minutes'] = watch['minutes_between_check']

    # Move the history list to a flat text file index
    # Better than SQLite because this list is only appended to, and works across NAS / NFS type setups
    def update_2(self):
        # @todo test running this on a newly updated one (when this already ran)
        for uuid, watch in self.data['watching'].items():
            history = []

            if watch.get('history', False):
                for d, p in watch['history'].items():
                    d = int(d)  # Used to be keyed as str, we'll fix this now too
                    history.append("{},{}\n".format(d,p))

                if len(history):
                    target_path = os.path.join(self.datastore_path, uuid)
                    if os.path.exists(target_path):
                        with open(os.path.join(target_path, "history.txt"), "w") as f:
                            f.writelines(history)
                    else:
                        logger.warning(f"Datastore history directory {target_path} does not exist, skipping history import.")

                # No longer needed, dynamically pulled from the disk when needed.
                # But we should set it back to a empty dict so we don't break if this schema runs on an earlier version.
                # In the distant future we can remove this entirely
                self.data['watching'][uuid]['history'] = {}

    # We incorrectly stored last_changed when there was not a change, and then confused the output list table
    def update_3(self):
        # see https://github.com/dgtlmoon/changedetection.io/pull/835
        return

    # `last_changed` not needed, we pull that information from the history.txt index
    def update_4(self):
        for uuid, watch in self.data['watching'].items():
            try:
                # Remove it from the struct
                del(watch['last_changed'])
            except:
                continue
        return

    def update_5(self):
        # If the watch notification body, title look the same as the global one, unset it, so the watch defaults back to using the main settings
        # In other words - the watch notification_title and notification_body are not needed if they are the same as the default one
        current_system_body = self.data['settings']['application']['notification_body'].translate(TRANSLATE_WHITESPACE_TABLE)
        current_system_title = self.data['settings']['application']['notification_body'].translate(TRANSLATE_WHITESPACE_TABLE)
        for uuid, watch in self.data['watching'].items():
            try:
                watch_body = watch.get('notification_body', '')
                if watch_body and watch_body.translate(TRANSLATE_WHITESPACE_TABLE) == current_system_body:
                    # Looks the same as the default one, so unset it
                    watch['notification_body'] = None

                watch_title = watch.get('notification_title', '')
                if watch_title and watch_title.translate(TRANSLATE_WHITESPACE_TABLE) == current_system_title:
                    # Looks the same as the default one, so unset it
                    watch['notification_title'] = None
            except Exception as e:
                continue
        return


    # We incorrectly used common header overrides that should only apply to Requests
    # These are now handled in content_fetcher::html_requests and shouldnt be passed to Playwright/Selenium
    def update_7(self):
        # These were hard-coded in early versions
        for v in ['User-Agent', 'Accept', 'Accept-Encoding', 'Accept-Language']:
            if self.data['settings']['headers'].get(v):
                del self.data['settings']['headers'][v]

    # Convert filters to a list of filters css_filter -> include_filters
    def update_8(self):
        for uuid, watch in self.data['watching'].items():
            try:
                existing_filter = watch.get('css_filter', '')
                if existing_filter:
                    watch['include_filters'] = [existing_filter]
            except:
                continue
        return

    # Convert old static notification tokens to jinja2 tokens
    def update_9(self):
        # Each watch
        import re
        # only { } not {{ or }}
        r = r'(?<!{){(?!{)(\w+)(?<!})}(?!})'
        for uuid, watch in self.data['watching'].items():
            try:
                n_body = watch.get('notification_body', '')
                if n_body:
                    watch['notification_body'] = re.sub(r, r'{{\1}}', n_body)

                n_title = watch.get('notification_title')
                if n_title:
                    watch['notification_title'] = re.sub(r, r'{{\1}}', n_title)

                n_urls = watch.get('notification_urls')
                if n_urls:
                    for i, url in enumerate(n_urls):
                        watch['notification_urls'][i] = re.sub(r, r'{{\1}}', url)

            except:
                continue

        # System wide
        n_body = self.data['settings']['application'].get('notification_body')
        if n_body:
            self.data['settings']['application']['notification_body'] = re.sub(r, r'{{\1}}', n_body)

        n_title = self.data['settings']['application'].get('notification_title')
        if n_body:
            self.data['settings']['application']['notification_title'] = re.sub(r, r'{{\1}}', n_title)

        n_urls =  self.data['settings']['application'].get('notification_urls')
        if n_urls:
            for i, url in enumerate(n_urls):
                self.data['settings']['application']['notification_urls'][i] = re.sub(r, r'{{\1}}', url)

        return

    # Some setups may have missed the correct default, so it shows the wrong config in the UI, although it will default to system-wide
    def update_10(self):
        for uuid, watch in self.data['watching'].items():
            try:
                if not watch.get('fetch_backend', ''):
                    watch['fetch_backend'] = 'system'
            except:
                continue
        return

    # Create tag objects and their references from existing tag text
    def update_12(self):
        i = 0
        for uuid, watch in self.data['watching'].items():
            # Split out and convert old tag string
            tag = watch.get('tag')
            if tag:
                tag_uuids = []
                for t in tag.split(','):
                    tag_uuids.append(self.add_tag(name=t))

                self.data['watching'][uuid]['tags'] = tag_uuids

    # #1775 - Update 11 did not update the records correctly when adding 'date_created' values for sorting
    def update_13(self):
        i = 0
        for uuid, watch in self.data['watching'].items():
            if not watch.get('date_created'):
                self.data['watching'][uuid]['date_created'] = i
            i+=1
        return

    # #1774 - protect xpath1 against migration
    def update_14(self):
        for awatch in self.__data["watching"]:
            if self.__data["watching"][awatch]['include_filters']:
                for num, selector in enumerate(self.__data["watching"][awatch]['include_filters']):
                    if selector.startswith('/'):
                        self.__data["watching"][awatch]['include_filters'][num] = 'xpath1:' + selector
                    if selector.startswith('xpath:'):
                        self.__data["watching"][awatch]['include_filters'][num] = selector.replace('xpath:', 'xpath1:', 1)

    # Use more obvious default time setting
    def update_15(self):
        for uuid in self.__data["watching"]:
            if self.__data["watching"][uuid]['time_between_check'] == self.__data['settings']['requests']['time_between_check']:
                # What the old logic was, which was pretty confusing
                self.__data["watching"][uuid]['time_between_check_use_default'] = True
            elif all(value is None or value == 0 for value in self.__data["watching"][uuid]['time_between_check'].values()):
                self.__data["watching"][uuid]['time_between_check_use_default'] = True
            else:
                # Something custom here
                self.__data["watching"][uuid]['time_between_check_use_default'] = False

    # Correctly set datatype for older installs where 'tag' was string and update_12 did not catch it
    def update_16(self):
        for uuid, watch in self.data['watching'].items():
            if isinstance(watch.get('tags'), str):
                self.data['watching'][uuid]['tags'] = []

    # Migrate old 'in_stock' values to the new Restock
    def update_17(self):
        for uuid, watch in self.data['watching'].items():
            if 'in_stock' in watch:
                watch['restock'] = Restock({'in_stock': watch.get('in_stock')})
                del watch['in_stock']

    # Migrate old restock settings
    def update_18(self):
        for uuid, watch in self.data['watching'].items():
            if not watch.get('restock_settings'):
                # So we enable price following by default
                self.data['watching'][uuid]['restock_settings'] = {'follow_price_changes': True}

            # Migrate and cleanoff old value
            self.data['watching'][uuid]['restock_settings']['in_stock_processing'] = 'in_stock_only' if watch.get(
                'in_stock_only') else 'all_changes'

            if self.data['watching'][uuid].get('in_stock_only'):
                del (self.data['watching'][uuid]['in_stock_only'])

    # Compress old elements.json to elements.deflate, saving disk, this compression is pretty fast.
    def update_19(self):
        import zlib

        for uuid, watch in self.data['watching'].items():
            json_path = os.path.join(self.datastore_path, uuid, "elements.json")
            deflate_path = os.path.join(self.datastore_path, uuid, "elements.deflate")

            if os.path.exists(json_path):
                with open(json_path, "rb") as f_j:
                    with open(deflate_path, "wb") as f_d:
                        logger.debug(f"Compressing {str(json_path)} to {str(deflate_path)}..")
                        f_d.write(zlib.compress(f_j.read()))
                        os.unlink(json_path)

