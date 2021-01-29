import json
import uuid as uuid_builder
import validators


# Is there an existing library to ensure some data store (JSON etc) is in sync with CRUD methods?
# Open a github issue if you know something :)
# https://stackoverflow.com/questions/6190468/how-to-trigger-function-on-value-change
class ChangeDetectionStore:

    def __init__(self):
        self.data = {
            'watching': {}
        }


        # Base definition for all watchers
        self.generic_definition = {
            'url': None,
            'tag': None,
            'last_checked': 0,
            'last_changed': 0,
            'title': None,
            'uuid': str(uuid_builder.uuid4()),
            'headers' : {}, # Extra headers to send
            'history' : {} # Dict of timestamp and output stripped filename
        }

        try:
            with open('/datastore/url-watches.json') as json_file:

                self.data.update(json.load(json_file))

                # Reinitialise each `watching` with our generic_definition in the case that we add a new var in the future.
                # @todo pretty sure theres a python we todo this with an abstracted(?) object!
                i = 0
                for uuid, watch in self.data['watching'].items():
                    _blank = self.generic_definition.copy()
                    _blank.update(watch)
                    self.data['watching'].update({uuid: _blank})
                    print("Watching:", uuid, _blank['url'])

        # First time ran, doesnt exist.
        except (FileNotFoundError, json.decoder.JSONDecodeError):
            print("Creating JSON store")

            self.add_watch(url='https://changedetection.io', tag='general')
            self.add_watch(url='http://www.quotationspage.com/random.php', tag='test')

    def update_watch(self, uuid, val, var):

        self.data['watching'][uuid].update({val: var})
        self.sync_to_json()



    def delete(self, uuid):
        # Probably their should be dict...
        del(self.data['watching'][uuid])
        self.sync_to_json()


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

        # @todo deal with exception
        validators.url(url)

        # @todo use a common generic version of this

        _blank = self.generic_definition.copy()
        _blank.update({
            'url': url,
            'tag': tag,
            'uuid': str(uuid_builder.uuid4())
        })

        self.data['watching'].update({_blank['uuid']: _blank})

        self.sync_to_json()

    def sync_to_json(self):
        with open('/datastore/url-watches.json', 'w') as json_file:
            json.dump(self.data, json_file, indent=4)

# body of the constructor
