from abc import ABC, abstractmethod


class Importer():
    remaining_data = []
    new_uuids = []

    @abstractmethod
    def run(self,
            data,
            flash,
            datastore):
        pass


class import_url_list(Importer):
    def run(self,
            data,
            flash,
            datastore,
            ):

        import validators
        import time
        urls = data.split("\n")
        good = 0
        now = time.time()

        if (len(urls) > 5000):
            flash("Importing 5,000 of the first URLs from your list, the rest can be imported again.")

        for url in urls:
            url = url.strip()
            url, *tags = url.split(" ")
            # Flask wtform validators wont work with basic auth, use validators package
            # Up to 5000 per batch so we dont flood the server
            if len(url) and validators.url(url.replace('source:', '')) and good < 5000:
                new_uuid = datastore.add_watch(url=url.strip(), tag=" ".join(tags), write_to_disk_now=False)
                if new_uuid:
                    # Straight into the queue.
                    self.new_uuids.append(new_uuid)
                    good += 1
                    continue

            if len(url.strip()):
                if self.remaining_data is None:
                    self.remaining_data = []
                self.remaining_data.append(url)

        flash("{} Imported in {:.2f}s, {} Skipped.".format(good, time.time() - now, len(self.remaining_data)))
        return self.new_uuids

class import_distill_io_json(Importer):
    def run(self,
            data,
            flash,
            datastore,
            ):
        x = 1
