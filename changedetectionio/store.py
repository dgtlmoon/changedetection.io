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
from os import mkdir, path, unlink
from threading import Lock
import re
import requests

from changedetectionio.model import Watch, App


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
        self.generic_definition = deepcopy(Watch.model())

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

                # Reinitialise each `watching` with our generic_definition in the case that we add a new var in the future.
                # @todo pretty sure theres a python we todo this with an abstracted(?) object!
                for uuid, watch in self.__data['watching'].items():
                    _blank = deepcopy(self.generic_definition)
                    _blank.update(watch)
                    self.__data['watching'].update({uuid: _blank})
                    self.__data['watching'][uuid]['newest_history_key'] = self.get_newest_history_key(uuid)
                    print("Watching:", uuid, self.__data['watching'][uuid]['url'])

        # First time ran, doesnt exist.
        except (FileNotFoundError, json.decoder.JSONDecodeError):
            if include_default_watches:
                print("Creating JSON store at", self.datastore_path)

                self.add_watch(url='http://www.quotationspage.com/random.php', tag='test')
                self.add_watch(url='https://news.ycombinator.com/', tag='Tech news')
                self.add_watch(url='https://www.gov.uk/coronavirus', tag='Covid')
                self.add_watch(url='https://changedetection.io/CHANGELOG.txt')

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
            import secrets
            secret = secrets.token_hex(16)
            self.__data['settings']['application']['rss_access_token'] = secret


        # Proxy list support - available as a selection in settings when text file is imported
        # CSV list
        # "name, address", or just "name"
        proxy_list_file = "{}/proxies.txt".format(self.datastore_path)
        if path.isfile(proxy_list_file):
            self.import_proxy_list(proxy_list_file)

        # Bump the update version by running updates
        self.run_updates()

        self.needs_write = True

        # Finally start the thread that will manage periodic data saves to JSON
        save_data_thread = threading.Thread(target=self.save_datastore).start()

    # Returns the newest key, but if theres only 1 record, then it's counted as not being new, so return 0.
    def get_newest_history_key(self, uuid):
        if len(self.__data['watching'][uuid]['history']) == 1:
            return 0

        dates = list(self.__data['watching'][uuid]['history'].keys())
        # Convert to int, sort and back to str again
        # @todo replace datastore getter that does this automatically
        dates = [int(i) for i in dates]
        dates.sort(reverse=True)
        if len(dates):
            # always keyed as str
            return str(dates[0])

        return 0

    def set_last_viewed(self, uuid, timestamp):
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
            self.__data['watching'][uuid]['newest_history_key'] = self.get_newest_history_key(uuid)

        self.needs_write = True

    @property
    def threshold_seconds(self):
        seconds = 0
        mtable = {'seconds': 1, 'minutes': 60, 'hours': 3600, 'days': 86400, 'weeks': 86400 * 7}
        minimum_seconds_recheck_time = int(os.getenv('MINIMUM_SECONDS_RECHECK_TIME', 60))
        for m, n in mtable.items():
            x = self.__data['settings']['requests']['time_between_check'].get(m)
            if x:
                seconds += x * n
        return max(seconds, minimum_seconds_recheck_time)

    @property
    def data(self):
        has_unviewed = False
        for uuid, v in self.__data['watching'].items():
            self.__data['watching'][uuid]['newest_history_key'] = self.get_newest_history_key(uuid)
            if int(v['newest_history_key']) <= int(v['last_viewed']):
                self.__data['watching'][uuid]['viewed'] = True

            else:
                self.__data['watching'][uuid]['viewed'] = False
                has_unviewed = True

            # #106 - Be sure this is None on empty string, False, None, etc
            # Default var for fetch_backend
            if not self.__data['watching'][uuid]['fetch_backend']:
                self.__data['watching'][uuid]['fetch_backend'] = self.__data['settings']['application']['fetch_backend']

        # Re #152, Return env base_url if not overriden, @todo also prefer the proxy pass url
        env_base_url = os.getenv('BASE_URL','')
        if not self.__data['settings']['application']['base_url']:
          self.__data['settings']['application']['base_url'] = env_base_url.strip('" ')

        self.__data['has_unviewed'] = has_unviewed

        return self.__data

    def get_all_tags(self):
        tags = []
        for uuid, watch in self.data['watching'].items():

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
                    for path in self.data['watching'][uuid]['history'].values():
                        self.unlink_history_file(path)

            else:
                for path in self.data['watching'][uuid]['history'].values():
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

    def get_val(self, uuid, val):
        # Probably their should be dict...
        return self.data['watching'][uuid].get(val)

    # Remove a watchs data but keep the entry (URL etc)
    def scrub_watch(self, uuid):
        import pathlib

        self.__data['watching'][uuid].update({'history': {}, 'last_checked': 0, 'last_changed': 0, 'newest_history_key': 0, 'previous_md5': False})
        self.needs_write_urgent = True

        for item in pathlib.Path(self.datastore_path).rglob(uuid+"/*.txt"):
            unlink(item)

    def add_watch(self, url, tag="", extras=None, write_to_disk_now=True):
        if extras is None:
            extras = {}
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

                # List of permisable stuff we accept from the wild internet
                for k in ['url', 'tag',
                                   'paused', 'title',
                                   'previous_md5', 'headers',
                                   'body', 'method',
                                   'ignore_text', 'css_filter',
                                   'subtractive_selectors', 'trigger_text',
                                   'extract_title_as_title']:
                    if res.get(k):
                        apply_extras[k] = res[k]

            except Exception as e:
                logging.error("Error fetching metadata for shared watch link", url, str(e))
                flash("Error fetching metadata for {}".format(url), 'error')
                return False

        with self.lock:
            # @todo use a common generic version of this
            new_uuid = str(uuid_builder.uuid4())
            # #Re 569
            # Not sure why deepcopy was needed here, sometimes new watches would appear to already have 'history' set
            # I assumed this would instantiate a new object but somehow an existing dict was getting used
            new_watch = deepcopy(Watch.model({
                'url': url,
                'tag': tag
            }))


            for k in ['uuid', 'history', 'last_checked', 'last_changed', 'newest_history_key', 'previous_md5', 'viewed']:
                if k in apply_extras:
                    del apply_extras[k]

            new_watch.update(apply_extras)
            self.__data['watching'][new_uuid]=new_watch

        # Get the directory ready
        output_path = "{}/{}".format(self.datastore_path, new_uuid)
        try:
            mkdir(output_path)
        except FileExistsError:
            print(output_path, "already exists.")

        if write_to_disk_now:
            self.sync_to_json()
        return new_uuid

    # Save some text file to the appropriate path and bump the history
    # result_obj from fetch_site_status.run()
    def save_history_text(self, watch_uuid, contents):
        import uuid

        output_path = "{}/{}".format(self.datastore_path, watch_uuid)
        # Incase the operator deleted it, check and create.
        if not os.path.isdir(output_path):
            mkdir(output_path)

        fname = "{}/{}.stripped.txt".format(output_path, uuid.uuid4())
        with open(fname, 'wb') as f:
            f.write(contents)
            f.close()

        return fname

    def get_screenshot(self, watch_uuid):
        output_path = "{}/{}".format(self.datastore_path, watch_uuid)
        fname = "{}/last-screenshot.png".format(output_path)
        if path.isfile(fname):
            return fname

        return False

    # Save as PNG, PNG is larger but better for doing visual diff in the future
    def save_screenshot(self, watch_uuid, screenshot: bytes):
        output_path = "{}/{}".format(self.datastore_path, watch_uuid)
        fname = "{}/last-screenshot.png".format(output_path)
        with open(fname, 'wb') as f:
            f.write(screenshot)
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
            for id in self.data['watching'][uuid]['history']:
                index.append(self.data['watching'][uuid]['history'][str(id)])

        import pathlib

        # Only in the sub-directories
        for uuid in self.data['watching']:
            for item in pathlib.Path(self.datastore_path).rglob(uuid+"/*.txt"):
                if not str(item) in index:
                    print ("Removing",item)
                    unlink(item)

    def import_proxy_list(self, filename):
        import csv
        with open(filename, newline='') as f:
            reader = csv.reader(f, skipinitialspace=True)
            # @todo This loop can could be improved
            l = []
            for row in reader:
                if len(row):
                    if len(row)>=2:
                        l.append(tuple(row[:2]))
                    else:
                        l.append(tuple([row[0], row[0]]))
            self.proxy_list = l if len(l) else None


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
