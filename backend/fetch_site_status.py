from threading import Thread
import time
import requests

import hashlib

# Hmm Polymorphism datastore, thread, etc
class perform_site_check(Thread):
    def __init__(self, *args, uuid=False, datastore, **kwargs):
        super().__init__(*args, **kwargs)
        self.timestamp = int(time.time()) # used for storage etc too
        self.uuid = uuid
        self.datastore = datastore
        self.url = datastore.get_val(uuid, 'url')
        self.current_md5 = datastore.get_val(uuid, 'previous_md5')

    def save_firefox_screenshot(self, uuid, output):
        #@todo call selenium or whatever
        return

    def save_response_output(self, output):
        # @todo maybe record a history.json, [timestamp, md5, filename]
        import os
        path = "/datastore/{}".format(self.uuid)
        try:
            os.stat(path)
        except:
            os.mkdir(path)

        with open("{}/{}.txt".format(path, self.timestamp), 'w') as f:
            f.write(output)
            f.close()


    def run(self):
        try:
            r = requests.get(self.url)
        except requests.exceptions.ConnectionError as e:
            self.datastore.update_watch(self.uuid, 'last_error', str(e))

            print (str(e))
        else:
            self.datastore.update_watch(self.uuid, 'last_error', False)
            self.datastore.update_watch(self.uuid, 'last_check_status', r.status_code)

            fetched_md5=hashlib.md5(r.text.encode('utf-8')).hexdigest()

            if self.current_md5 != fetched_md5:
                self.datastore.update_watch(self.uuid, 'previous_md5', fetched_md5)
                self.save_response_output(r.text)
                self.datastore.update_watch(self.uuid, 'last_changed', self.timestamp)

        self.datastore.update_watch(self.uuid, 'last_checked', int(time.time()))
        pass
