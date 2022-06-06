from abc import ABC, abstractmethod
import time
import validators


class Importer():
    remaining_data = []
    new_uuids = []
    good = 0

    def __init__(self):
        self.new_uuids = []
        self.good = 0
        self.remaining_data = []

    @abstractmethod
    def run(self,
            data,
            flash,
            datastore):
        pass


class import_url_list(Importer):
    """
    Imports a list, can be in <code>https://example.com tag1, tag2, last tag</code> format
    """
    def run(self,
            data,
            flash,
            datastore,
            ):

        urls = data.split("\n")
        good = 0
        now = time.time()

        if (len(urls) > 5000):
            flash("Importing 5,000 of the first URLs from your list, the rest can be imported again.")

        for url in urls:
            url = url.strip()
            if not len(url):
                continue

            tags = ""

            # 'tags' should be a csv list after the URL
            if ' ' in url:
                url, tags = url.split(" ", 1)

            # Flask wtform validators wont work with basic auth, use validators package
            # Up to 5000 per batch so we dont flood the server
            if len(url) and validators.url(url.replace('source:', '')) and good < 5000:
                new_uuid = datastore.add_watch(url=url.strip(), tag=tags, write_to_disk_now=False)
                if new_uuid:
                    # Straight into the queue.
                    self.new_uuids.append(new_uuid)
                    good += 1
                    continue

            # Worked past the 'continue' above, append it to the bad list
            if self.remaining_data is None:
                self.remaining_data = []
            self.remaining_data.append(url)

        flash("{} Imported from list in {:.2f}s, {} Skipped.".format(good, time.time() - now, len(self.remaining_data)))


class import_distill_io_json(Importer):
    def run(self,
            data,
            flash,
            datastore,
            ):

        import json
        good = 0
        now = time.time()
        self.new_uuids=[]


        try:
            data = json.loads(data.strip())
        except json.decoder.JSONDecodeError:
            flash("Unable to read JSON file, was it broken?", 'error')
            return

        if not data.get('data'):
            flash("JSON structure looks invalid, was it broken?", 'error')
            return

        for d in data.get('data'):
            d_config = json.loads(d['config'])
            extras = {'title': d.get('name', None)}

            if len(d['uri']) and good < 5000:
                try:
                    # @todo we only support CSS ones at the moment
                    if d_config['selections'][0]['frames'][0]['excludes'][0]['type'] == 'css':
                        extras['subtractive_selectors'] = d_config['selections'][0]['frames'][0]['excludes'][0]['expr']
                except KeyError:
                    pass
                except IndexError:
                    pass

                try:
                    extras['css_filter'] = d_config['selections'][0]['frames'][0]['includes'][0]['expr']
                    if d_config['selections'][0]['frames'][0]['includes'][0]['type'] == 'xpath':
                        extras['css_filter'] = 'xpath:' + extras['css_filter']

                except KeyError:
                    pass
                except IndexError:
                    pass


                if d.get('tags', False):
                    extras['tag'] = ", ".join(d['tags'])

                new_uuid = datastore.add_watch(url=d['uri'].strip(),
                                               extras=extras,
                                               write_to_disk_now=False)

                if new_uuid:
                    # Straight into the queue.
                    self.new_uuids.append(new_uuid)
                    good += 1

        flash("{} Imported from Distill.io in {:.2f}s, {} Skipped.".format(len(self.new_uuids), time.time() - now, len(self.remaining_data)))
