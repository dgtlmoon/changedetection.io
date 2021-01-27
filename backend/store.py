import json
import uuid
import validators


# Is there an existing library to ensure some data store (JSON etc) is in sync with CRUD methods?
# Open a github issue if you know something :)
# https://stackoverflow.com/questions/6190468/how-to-trigger-function-on-value-change
class ChangeDetectionStore:

    def __init__(self):

        # Base definition for all watchers
        self.generic_definition = {
            'url': None,
            'tag': None,
            'last_checked': 0,
            'last_changed': 0,
            'title': None,
            'uuid': str(uuid.uuid4()),
            'headers' : {}
        }

        try:
            with open('/datastore/url-watches.json') as json_file:
                self.data = json.load(json_file)
                # Reinitialise each `watching` with our generic_definition in the case that we add a new var in the future.
                i = 0
                while i < len(self.data['watching']):
                    _blank = self.generic_definition.copy()
                    _blank.update(self.data['watching'][i])
                    self.data['watching'][i] = _blank

                    print("Watching:", self.data['watching'][i]['url'])
                    i += 1

        # First time ran, doesnt exist.
        except (FileNotFoundError, json.decoder.JSONDecodeError):
            print("Resetting JSON store")

            self.data = {}
            self.data['watching'] = []
            self._init_blank_data()
            self.sync_to_json()

    def _init_blank_data(self):

        # Test site
        _blank = self.generic_definition.copy()
        _blank.update({
            'url': 'https://changedetection.io',
            'tag': 'general',
            'uuid': str(uuid.uuid4())
        })
        self.data['watching'].append(_blank)

        # Test site
        _blank = self.generic_definition.copy()
        _blank.update({
            'url': 'http://www.quotationspage.com/random.php',
            'tag': 'test',
            'uuid': str(uuid.uuid4())
        })
        self.data['watching'].append(_blank)

    def update_watch(self, uuid, val, var):
        # Probably their should be dict...
        for watch in self.data['watching']:
            if watch['uuid'] == uuid:
                watch[val] = var
                # print("Updated..", val)
                self.sync_to_json()

    def url_exists(self, url):

        # Probably their should be dict...
        for watch in self.data['watching']:
            if watch['url'] == url:
                return True

        return False

    def get_val(self, uuid, val):
        # Probably their should be dict...
        for watch in self.data['watching']:
            if watch['uuid'] == uuid:
                if val in watch:
                    return watch[val]
                else:
                    return None

        return None

    def add_watch(self, url, tag):
        validators.url(url)

        # @todo use a common generic version of this

        _blank = self.generic_definition.copy()
        _blank.update({
            'url': url,
            'tag': tag,
            'uuid': str(uuid.uuid4())
        })
        self.data['watching'].append(_blank)

        self.sync_to_json()
        # @todo throw custom exception

    def sync_to_json(self):
        with open('/datastore/url-watches.json', 'w') as json_file:
            json.dump(self.data, json_file, indent=4)

# body of the constructor
