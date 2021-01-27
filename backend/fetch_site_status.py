from threading import Thread
import time
import requests
import hashlib


# Hmm Polymorphism datastore, thread, etc
class perform_site_check(Thread):
    def __init__(self, *args, uuid=False, datastore, **kwargs):
        super().__init__(*args, **kwargs)
        self.timestamp = int(time.time())  # used for storage etc too
        self.uuid = uuid
        self.datastore = datastore
        self.url = datastore.get_val(uuid, 'url')
        self.current_md5 = datastore.get_val(uuid, 'previous_md5')

    def save_firefox_screenshot(self, uuid, output):
        # @todo call selenium or whatever
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

        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.66 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'en-GB,en-US;q=0.9,en;q=0.8,cs;q=0.7'
        }


        print("Checking", self.url)
        import html2text

        try:
            r = requests.get(self.url, headers=headers, timeout=15)

            stripped_text_from_html = html2text.html2text(r.content.decode('utf-8'))
        # Usually from networkIO/requests level
        except (requests.exceptions.ConnectionError,requests.exceptions.ReadTimeout) as e:
            self.datastore.update_watch(self.uuid, 'last_error', str(e))
            print(str(e))


        # Usually from html2text level
        except UnicodeDecodeError as e:
            self.datastore.update_watch(self.uuid, 'last_error', str(e))
            print(str(e))

        else:

            # We rely on the actual text in the html output.. many sites have random script vars etc




            self.datastore.update_watch(self.uuid, 'last_error', False)
            self.datastore.update_watch(self.uuid, 'last_check_status', r.status_code)

            fetched_md5 = hashlib.md5(stripped_text_from_html.encode('utf-8')).hexdigest()

            if self.current_md5 != fetched_md5:
                self.datastore.update_watch(self.uuid, 'previous_md5', fetched_md5)
                self.save_response_output(r.text)
                self.datastore.update_watch(self.uuid, 'last_changed', self.timestamp)

        self.datastore.update_watch(self.uuid, 'last_checked', int(time.time()))
        pass
