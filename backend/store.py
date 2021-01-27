import json
import uuid
import validators


# @TODO Have a var which is the base value, this is referred to even in the templating.. merge and append,not just append
# Is there an existing library to ensure some data store (JSON etc) is in sync with CRUD methods?
# Open a github issue if you know something :)
# https://stackoverflow.com/questions/6190468/how-to-trigger-function-on-value-change
class ChangeDetectionStore:

    def __init__(self):
        try:
            with open('/datastore/url-watches.json') as json_file:
                self.data = json.load(json_file)
                for p in self.data['watching']:
                    print("Watching:", p['url'])

        # First time ran, doesnt exist.
        except (FileNotFoundError, json.decoder.JSONDecodeError):
            print ("Resetting JSON store")

            self.data = {}
            self.data['watching'] = []
            self.data['watching'].append({
                'url': 'https://changedetection.io',
                'tag': 'general',
                'last_checked': 0,
                'last_changed' : 0,
                'uuid': str(uuid.uuid4())
            })
            self.data['watching'].append({
                'url': 'http://www.quotationspage.com/random.php',
                'tag': 'test',
                'last_checked': 0,
                'last_changed' : 0,
                'uuid': str(uuid.uuid4())
            })


            with open('/datastore/url-watches.json', 'w') as json_file:
                json.dump(self.data, json_file)

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
        self.data['watching'].append({
            'url': url,
            'tag': tag,
            'last_checked':0,
            'last_changed': 0,
            'uuid': str(uuid.uuid4())
        })
        self.sync_to_json()
        # @todo throw custom exception

    def sync_to_json(self):
        with open('/datastore/url-watches.json', 'w') as json_file:
            json.dump(self.data, json_file, indent=4)

# body of the constructor