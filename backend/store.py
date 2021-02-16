import json
import uuid as uuid_builder
import validators
import os.path
from os import path
from threading import Lock, Thread

from copy import deepcopy

import logging
import time
import threading

# Is there an existing library to ensure some data store (JSON etc) is in sync with CRUD methods?
# Open a github issue if you know something :)
# https://stackoverflow.com/questions/6190468/how-to-trigger-function-on-value-change
class ChangeDetectionStore:
    lock = Lock()

    def __init__(self, datastore_path="/datastore"):
        self.needs_write = False
        self.datastore_path = datastore_path
        self.json_store_path = "{}/url-watches.json".format(self.datastore_path)
        self.stop_thread = False
        self.__data = {
            'note': "Hello! If you change this file manually, please be sure to restart your changedetection.io instance!",
            'watching': {},
            'tag': "0.24",
            'settings': {
                'headers': {
                    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.66 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
                    'Accept-Encoding': 'gzip, deflate',  # No support for brolti in python requests yet.
                    'Accept-Language': 'en-GB,en-US;q=0.9,en;'
                },
                'requests': {
                    'timeout': 15,  # Default 15 seconds
                    'minutes_between_check': 3 * 60,  # Default 3 hours
                    'workers': 10  # Number of threads, lower is better for slow connections
                }
            }
        }

        # Base definition for all watchers
        self.generic_definition = {
            'url': None,
            'tag': None,
            'last_checked': 0,
            'last_changed': 0,
            'last_viewed': 0,  # history key value of the last viewed via the [diff] link
            'newest_history_key': "",
            'title': None,
            'previous_md5': "",
            'uuid': str(uuid_builder.uuid4()),
            'headers': {},  # Extra headers to send
            'history': {}  # Dict of timestamp and output stripped filename
        }

        if path.isfile('/source.txt'):
            with open('/source.txt') as f:
                # Should be set in Dockerfile to look for /source.txt , this will give us the git commit #
                # So when someone gives us a backup file to examine, we know exactly what code they were running.
                self.__data['build_sha'] = f.read()

        try:
            with open(self.json_store_path) as json_file:
                from_disk = json.load(json_file)

                # @todo isnt there a way todo this dict.update recursively?
                # Problem here is if the one on the disk is missing a sub-struct, it wont be present anymore.
                if 'watching' in from_disk:
                    self.__data['watching'].update(from_disk['watching'])

                if 'settings' in from_disk:
                    if 'headers' in from_disk['settings']:
                        self.__data['settings']['headers'].update(from_disk['settings']['headers'])

                    if 'requests' in from_disk['settings']:
                        self.__data['settings']['requests'].update(from_disk['settings']['requests'])

                # Reinitialise each `watching` with our generic_definition in the case that we add a new var in the future.
                # @todo pretty sure theres a python we todo this with an abstracted(?) object!

                for uuid, watch in self.data['watching'].items():
                    _blank = deepcopy(self.generic_definition)
                    _blank.update(watch)
                    self.__data['watching'].update({uuid: _blank})
                    self.__data['watching'][uuid]['newest_history_key'] = self.get_newest_history_key(uuid)
                    print("Watching:", uuid, self.__data['watching'][uuid]['url'])

        # First time ran, doesnt exist.
        except (FileNotFoundError, json.decoder.JSONDecodeError):
            print("Creating JSON store at", self.datastore_path)
            self.add_watch(url='http://www.quotationspage.com/random.php', tag='test')
            self.add_watch(url='https://news.ycombinator.com/', tag='Tech news')
            self.add_watch(url='https://www.gov.uk/coronavirus', tag='Covid')
            self.add_watch(url='https://changedetection.io', tag='Tech news')

        # Finally start the thread that will manage periodic data saves to JSON
        save_data_thread = threading.Thread(target=self.save_datastore).start()

    # Returns the newest key, but if theres only 1 record, then it's counted as not being new, so return 0.
    def get_newest_history_key(self, uuid):
        if len(self.__data['watching'][uuid]['history']) == 1:
            return 0

        dates = list(self.__data['watching'][uuid]['history'].keys())
        # Convert to int, sort and back to str again
        dates = [int(i) for i in dates]
        dates.sort(reverse=True)
        if len(dates):
            # always keyed as str
            return str(dates[0])

        return 0

    def set_last_viewed(self, uuid, timestamp):
        self.data['watching'][uuid].update({'last_viewed': str(timestamp)})
        self.needs_write = True

    def update_watch(self, uuid, update_obj):

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
    def data(self):

        return self.__data

    def get_all_tags(self):
        tags = []
        for uuid, watch in self.data['watching'].items():

            # Support for comma separated list of tags.
            for tag in watch['tag'].split(','):
                tag = tag.strip()
                if not tag in tags:
                    tags.append(tag)

        tags.sort()
        return tags

    def delete(self, uuid):
        with self.lock:
            del (self.__data['watching'][uuid])
            self.needs_write = True

    def url_exists(self, url):

        # Probably their should be dict...
        for watch in self.data['watching']:
            if watch['url'] == url:
                return True

        return False

    def get_val(self, uuid, val):
        # Probably their should be dict...
        return self.data['watching'][uuid].get(val)

    def add_watch(self, url, tag):
        with self.lock:
            # @todo use a common generic version of this
            new_uuid = str(uuid_builder.uuid4())
            _blank = deepcopy(self.generic_definition)
            _blank.update({
                'url': url,
                'tag': tag,
                'uuid': new_uuid
            })

            self.data['watching'][new_uuid] = _blank

        # Get the directory ready
        output_path = "{}/{}".format(self.datastore_path, new_uuid)
        try:
            os.mkdir(output_path)
        except FileExistsError:
            print(output_path, "already exists.")

        self.sync_to_json()
        return new_uuid

    # Save some text file to the appropriate path and bump the history
    # result_obj from fetch_site_status.run()
    def save_history_text(self, uuid, result_obj, contents):

        output_path = "{}/{}".format(self.datastore_path, uuid)
        fname = "{}/{}.stripped.txt".format(output_path, result_obj['previous_md5'])
        with open(fname, 'w') as f:
            f.write(contents)
            f.close()

        # Update history with the stripped text for future reference, this will also mean we save the first
        # Should always be keyed by string(timestamp)
        self.update_watch(uuid, {"history": {str(result_obj["last_checked"]): fname}})

        return fname

    def sync_to_json(self):
        print ("Saving..")
        with open(self.json_store_path, 'w') as json_file:
            json.dump(self.__data, json_file, indent=4)
            logging.info("Re-saved index")

        self.needs_write = False

    # Thread runner, this helps with thread/write issues when there are many operations that want to update the JSON
    # by just running periodically in one thread, according to python, dict updates are threadsafe.
    def save_datastore(self):

        while True:
            if self.stop_thread:
                print ("Shutting down datastore thread")
                return
            if self.needs_write:
                self.sync_to_json()
            time.sleep(1)


# body of the constructor
