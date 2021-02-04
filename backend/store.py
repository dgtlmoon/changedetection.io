import json
import uuid as uuid_builder
import validators
import os.path
from os import path
from threading import Lock, Thread


# Is there an existing library to ensure some data store (JSON etc) is in sync with CRUD methods?
# Open a github issue if you know something :)
# https://stackoverflow.com/questions/6190468/how-to-trigger-function-on-value-change
class ChangeDetectionStore:
    lock = Lock()

    def __init__(self):
        self.needs_write = False

        self.__data = {
            'note': "Hello! If you change this file manually, please be sure to restart your changedetection.io instance!",
            'watching': {},
            'tag': "0.23",
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
            'title': None,
            'previous_md5': None,
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
            with open('/datastore/url-watches.json') as json_file:
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
                i = 0
                for uuid, watch in self.data['watching'].items():
                    _blank = self.generic_definition.copy()
                    _blank.update(watch)
                    self.__data['watching'].update({uuid: _blank})
                    print("Watching:", uuid, _blank['url'])

        # First time ran, doesnt exist.
        except (FileNotFoundError, json.decoder.JSONDecodeError):
            print("Creating JSON store")
            self.add_watch(url='http://www.quotationspage.com/random.php', tag='test')
            self.add_watch(url='https://news.ycombinator.com/', tag='Tech news')
            self.add_watch(url='https://www.gov.uk/coronavirus', tag='Covid')
            self.add_watch(url='https://changedetection.io', tag='Tech news')

    def update_watch(self, uuid, update_obj):

        self.lock.acquire()

        # In python 3.9 we have the |= dict operator, but that still will lose data on nested structures...
        for dict_key, d in self.generic_definition.items():
            if isinstance(d, dict) and dict_key in update_obj:
                self.__data['watching'][uuid][dict_key].update(update_obj[dict_key])
                del(update_obj[dict_key])

        # Update with the remaining values
        self.__data['watching'][uuid].update(update_obj)

        self.needs_write = True
        self.lock.release()

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

        self.lock.acquire()
        del (self.__data['watching'][uuid])
        self.needs_write = True
        self.lock.release()

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
        self.lock.acquire()
        print("Adding", url, tag)
        #        # @todo deal with exception
        #        validators.url(url)

        # @todo use a common generic version of this
        new_uuid = str(uuid_builder.uuid4())
        _blank = self.generic_definition.copy()
        _blank.update({
            'url': url,
            'tag': tag,
            'uuid': new_uuid
        })

        self.data['watching'][new_uuid] = _blank
        self.needs_write = True
        self.lock.release()
        return new_uuid

    def sync_to_json(self):
        print("Saving index")
        self.lock.acquire()
        with open('/datastore/url-watches.json', 'w') as json_file:
            json.dump(self.data, json_file, indent=4)
        self.needs_write = False
        self.lock.release()

# body of the constructor
