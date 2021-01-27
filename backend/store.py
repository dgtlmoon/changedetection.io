import json
import uuid
# Is there an existing library to ensure some data store (JSON etc) is in sync with CRUD methods?
# Open a github issue if you know something :)

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
                'uuid': str(uuid.uuid4())
            })

            with open('/datastore/url-watches.json', 'w') as json_file:
                json.dump(self.data, json_file)



    def sync_to_json(self):
        with open('/datastore/url-watches.json', 'w') as json_file:
            json.dump(self.data, json_file)

# body of the constructor