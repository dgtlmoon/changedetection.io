import json
import uuid
import validators

# Is there an existing library to ensure some data store (JSON etc) is in sync with CRUD methods?
# Open a github issue if you know something :)
# https://stackoverflow.com/questions/6190468/how-to-trigger-function-on-value-change
class ChangeDetectionStore:

    def __init__(self):
        try:
            with open('/datastore/url-watches.json') as json_file:
                self.data = json.load(json_file)
                for p in self.data['watching']:
                    print('url: ' + p['url'])
                    print('')

        # First time ran, doesnt exist.
        except (FileNotFoundError, json.decoder.JSONDecodeError):
            print ("Resetting JSON store")

            self.data = {}
            self.data['watching'] = []
            self.data['watching'].append({
                'url': 'https://changedetection.io',
                'tag': 'general',
                'last_checked': 0,
                'uuid': str(uuid.uuid4())
            })

            with open('/datastore/url-watches.json', 'w') as json_file:
                json.dump(self.data, json_file)


    def add_watch(self, url, tag):
        validators.url(url)

        self.data['watching'].append({
            'url': url,
            'tag': tag,
            'uuid': str(uuid.uuid4())
        })
        self.sync_to_json()
        # @todo throw custom exception

    def sync_to_json(self):
        with open('/datastore/url-watches.json', 'w') as json_file:
            json.dump(self.data, json_file)

# body of the constructor