from flask import (
    flash
)
import json
import logging
import os
import threading
import time
import uuid as uuid_builder
from copy import deepcopy
from os import path, unlink
from threading import Lock
import re
import requests
import secrets

from . model import App, Watch

# Is there an existing library to ensure some data store (JSON etc) is in sync with CRUD methods?
# Open a github issue if you know something :)
# https://stackoverflow.com/questions/6190468/how-to-trigger-function-on-value-change
class ChangeDetectionStore:
    lock = Lock()
    # For general updates/writes that can wait a few seconds
    needs_write = False

    # For when we edit, we should write to disk
    needs_write_urgent = False

    def __init__(self, datastore_path="/datastore", include_default_watches=True, version_tag="0.0.0"):
        # Should only be active for docker
        # logging.basicConfig(filename='/dev/stdout', level=logging.INFO)
        self.needs_write = False
        self.datastore_path = datastore_path
        self.json_store_path = "{}/url-watches.json".format(self.datastore_path)
        self.proxy_list = None
        self.stop_thread = False

        self.__data = App.model()

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
                    watch['uuid']=uuid
                    self.__data['watching'][uuid] = Watch.model(datastore_path=self.datastore_path, default=watch)
                    print("Watching:", uuid, self.__data['watching'][uuid]['url'])

        # First time ran, doesnt exist.
        except (FileNotFoundError, json.decoder.JSONDecodeError):
            if include_default_watches:
                print("Creating JSON store at", self.datastore_path)
                self.add_watch(url='https://news.ycombinator.com/', tag='Tech news')
                self.add_watch(url='https://changedetection.io/CHANGELOG.txt', tag='changedetection.io')

        self.__data['version_tag'] = version_tag

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
        if not 'rss_access_token' in self.__data['settings']['application']:
            secret = secrets.token_hex(16)
            self.__data['settings']['application']['rss_access_token'] = secret

        # Generate the API access token
        if not 'api_access_token' in self.__data['settings']['application']:
            secret = secrets.token_hex(16)
            self.__data['settings']['application']['api_access_token'] = secret

        # Proxy list support - available as a selection in settings when text file is imported
        proxy_list_file = "{}/proxies.json".format(self.datastore_path)
        if path.isfile(proxy_list_file):
            self.import_proxy_list(proxy_list_file)

        # Bump the update version by running updates
        self.run_updates()

        self.needs_write = True

        # Finally start the thread that will manage periodic data saves to JSON
        save_data_thread = threading.Thread(target=self.save_datastore).start()

    def set_last_viewed(self, uuid, timestamp):
        logging.debug("Setting watch UUID: {} last viewed to {}".format(uuid, int(timestamp)))
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
        for uuid, watch in self.__data['watching'].items():
            if watch.viewed == False:
                return True
        return False

    @property
    def data(self):
        has_unviewed = False
        for uuid, watch in self.__data['watching'].items():
            # #106 - Be sure this is None on empty string, False, None, etc
            # Default var for fetch_backend
            # @todo this may not be needed anymore, or could be easily removed
            if not self.__data['watching'][uuid]['fetch_backend']:
                self.__data['watching'][uuid]['fetch_backend'] = self.__data['settings']['application']['fetch_backend']

        # Re #152, Return env base_url if not overriden, @todo also prefer the proxy pass url
        env_base_url = os.getenv('BASE_URL','')
        if not self.__data['settings']['application']['base_url']:
          self.__data['settings']['application']['base_url'] = env_base_url.strip('" ')

        return self.__data

    def get_all_tags(self):
        tags = []
        for uuid, watch in self.data['watching'].items():
            if watch['tag'] is None:
                continue
            # Support for comma separated list of tags.
            for tag in watch['tag'].split(','):
                tag = tag.strip()
                if tag not in tags:
                    tags.append(tag)

        tags.sort()
        return tags

    def unlink_history_file(self, path):
        try:
            unlink(path)
        except (FileNotFoundError, IOError):
            pass

    # Delete a single watch by UUID
    def delete(self, uuid):
        with self.lock:
            if uuid == 'all':
                self.__data['watching'] = {}

                # GitHub #30 also delete history records
                for uuid in self.data['watching']:
                    for path in self.data['watching'][uuid].history.values():
                        self.unlink_history_file(path)

            else:
                for path in self.data['watching'][uuid].history.values():
                    self.unlink_history_file(path)

                del self.data['watching'][uuid]

            self.needs_write_urgent = True

    # Clone a watch by UUID
    def clone(self, uuid):
        url = self.data['watching'][uuid]['url']
        tag = self.data['watching'][uuid]['tag']
        extras = self.data['watching'][uuid]
        new_uuid = self.add_watch(url=url, tag=tag, extras=extras)
        return new_uuid

    def url_exists(self, url):

        # Probably their should be dict...
        for watch in self.data['watching'].values():
            if watch['url'] == url:
                return True

        return False

    # Remove a watchs data but keep the entry (URL etc)
    def clear_watch_history(self, uuid):
        import pathlib

        self.__data['watching'][uuid].update(
            {'last_checked': 0,
             'last_viewed': 0,
             'previous_md5': False,
             'last_notification_error': False,
             'last_error': False})

        # JSON Data, Screenshots, Textfiles (history index and snapshots), HTML in the future etc
        for item in pathlib.Path(os.path.join(self.datastore_path, uuid)).rglob("*.*"):
            unlink(item)

        # Force the attr to recalculate
        bump = self.__data['watching'][uuid].history

        self.needs_write_urgent = True

    def add_watch(self, url, tag="", extras=None, write_to_disk_now=True):

        if extras is None:
            extras = {}
        # should always be str
        if tag is None or not tag:
            tag=''

        # Incase these are copied across, assume it's a reference and deepcopy()
        apply_extras = deepcopy(extras)

        # Was it a share link? try to fetch the data
        if (url.startswith("https://changedetection.io/share/")):
            try:
                r = requests.request(method="GET",
                                     url=url,
                                     # So we know to return the JSON instead of the human-friendly "help" page
                                     headers={'App-Guid': self.__data['app_guid']})
                res = r.json()

                # List of permissible attributes we accept from the wild internet
                for k in ['url', 'tag',
                          'paused', 'title',
                          'previous_md5', 'headers',
                          'body', 'method',
                          'ignore_text', 'css_filter',
                          'subtractive_selectors', 'trigger_text',
                          'extract_title_as_title', 'extract_text',
                          'text_should_not_be_present',
                          'webdriver_js_execute_code']:
                    if res.get(k):
                        apply_extras[k] = res[k]

            except Exception as e:
                logging.error("Error fetching metadata for shared watch link", url, str(e))
                flash("Error fetching metadata for {}".format(url), 'error')
                return False

        with self.lock:

            # #Re 569
            new_watch = Watch.model(datastore_path=self.datastore_path, default={
                'url': url,
                'tag': tag
            })

            new_uuid = new_watch['uuid']
            logging.debug("Added URL {} - {}".format(url, new_uuid))

            for k in ['uuid', 'history', 'last_checked', 'last_changed', 'newest_history_key', 'previous_md5', 'viewed']:
                if k in apply_extras:
                    del apply_extras[k]

            new_watch.update(apply_extras)
            self.__data['watching'][new_uuid]=new_watch

        self.__data['watching'][new_uuid].ensure_data_dir_exists()

        if write_to_disk_now:
            self.sync_to_json()
        return new_uuid

    def visualselector_data_is_ready(self, watch_uuid):
        output_path = "{}/{}".format(self.datastore_path, watch_uuid)
        screenshot_filename = "{}/last-screenshot.png".format(output_path)
        elements_index_filename = "{}/elements.json".format(output_path)
        if path.isfile(screenshot_filename) and  path.isfile(elements_index_filename) :
            return True

        return False

    # Save as PNG, PNG is larger but better for doing visual diff in the future
    def save_screenshot(self, watch_uuid, screenshot: bytes, as_error=False):
        if not self.data['watching'].get(watch_uuid):
            return

        if as_error:
            target_path = os.path.join(self.datastore_path, watch_uuid, "last-error-screenshot.png")
        else:
            target_path = os.path.join(self.datastore_path, watch_uuid, "last-screenshot.png")

        self.data['watching'][watch_uuid].ensure_data_dir_exists()

        with open(target_path, 'wb') as f:
            f.write(screenshot)
            f.close()

    def save_error_text(self, watch_uuid, contents):
        if not self.data['watching'].get(watch_uuid):
            return
        target_path = os.path.join(self.datastore_path, watch_uuid, "last-error.txt")

        with open(target_path, 'w') as f:
            f.write(contents)

    def save_xpath_data(self, watch_uuid, data, as_error=False):
        if not self.data['watching'].get(watch_uuid):
            return
        if as_error:
            target_path = os.path.join(self.datastore_path, watch_uuid, "elements-error.json")
        else:
            target_path = os.path.join(self.datastore_path, watch_uuid, "elements.json")

        with open(target_path, 'w') as f:
            f.write(json.dumps(data))
            f.close()


    def sync_to_json(self):
        logging.info("Saving JSON..")
        print("Saving JSON..")
        try:
            data = deepcopy(self.__data)
        except RuntimeError as e:
            # Try again in 15 seconds
            time.sleep(15)
            logging.error ("! Data changed when writing to JSON, trying again.. %s", str(e))
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
                logging.error("Error writing JSON!! (Main JSON file save was skipped) : %s", str(e))

            self.needs_write = False
            self.needs_write_urgent = False

    # Thread runner, this helps with thread/write issues when there are many operations that want to update the JSON
    # by just running periodically in one thread, according to python, dict updates are threadsafe.
    def save_datastore(self):

        while True:
            if self.stop_thread:
                print("Shutting down datastore thread")
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
        print ("Removing snapshots from datastore that are not in the index..")

        index=[]
        for uuid in self.data['watching']:
            for id in self.data['watching'][uuid].history:
                index.append(self.data['watching'][uuid].history[str(id)])

        import pathlib

        # Only in the sub-directories
        for uuid in self.data['watching']:
            for item in pathlib.Path(self.datastore_path).rglob(uuid+"/*.txt"):
                if not str(item) in index:
                    print ("Removing",item)
                    unlink(item)

    def import_proxy_list(self, filename):
        with open(filename) as f:
            self.proxy_list = json.load(f)
            print ("Registered proxy list", list(self.proxy_list.keys()))


    def get_preferred_proxy_for_watch(self, uuid):
        """
        Returns the preferred proxy by ID key
        :param uuid: UUID
        :return: proxy "key" id
        """

        proxy_id = None
        if self.proxy_list is None:
            return None

        # If its a valid one
        watch = self.data['watching'].get(uuid)

        if watch.get('proxy') and watch.get('proxy') in list(self.proxy_list.keys()):
            return watch.get('proxy')

        # not valid (including None), try the system one
        else:
            system_proxy_id = self.data['settings']['requests'].get('proxy')
            # Is not None and exists
            if self.proxy_list.get(system_proxy_id):
                return system_proxy_id

        # Fallback - Did not resolve anything, use the first available
        if system_proxy_id is None:
            first_default = list(self.proxy_list)[0]
            return first_default

        return None

    # Run all updates
    # IMPORTANT - Each update could be run even when they have a new install and the schema is correct
    #             So therefor - each `update_n` should be very careful about checking if it needs to actually run
    #             Probably we should bump the current update schema version with each tag release version?
    def run_updates(self):
        import inspect
        import shutil

        updates_available = []
        for i, o in inspect.getmembers(self, predicate=inspect.ismethod):
            m = re.search(r'update_(\d+)$', i)
            if m:
                updates_available.append(int(m.group(1)))
        updates_available.sort()

        for update_n in updates_available:
            if update_n > self.__data['settings']['application']['schema_version']:
                print ("Applying update_{}".format((update_n)))
                # Wont exist on fresh installs
                if os.path.exists(self.json_store_path):
                    shutil.copyfile(self.json_store_path, self.datastore_path+"/url-watches-before-{}.json".format(update_n))

                try:
                    update_method = getattr(self, "update_{}".format(update_n))()
                except Exception as e:
                    print("Error while trying update_{}".format((update_n)))
                    print(e)
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
                        logging.warning("Datastore history directory {} does not exist, skipping history import.".format(target_path))

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
        current_system_body = self.data['settings']['application']['notification_body'].translate(str.maketrans('', '', "\r\n "))
        current_system_title = self.data['settings']['application']['notification_body'].translate(str.maketrans('', '', "\r\n "))
        for uuid, watch in self.data['watching'].items():
            try:
                watch_body = watch.get('notification_body', '')
                if watch_body and watch_body.translate(str.maketrans('', '', "\r\n ")) == current_system_body:
                    # Looks the same as the default one, so unset it
                    watch['notification_body'] = None

                watch_title = watch.get('notification_title', '')
                if watch_title and watch_title.translate(str.maketrans('', '', "\r\n ")) == current_system_title:
                    # Looks the same as the default one, so unset it
                    watch['notification_title'] = None
            except Exception as e:
                continue
        return

