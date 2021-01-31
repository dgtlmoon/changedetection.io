from threading import Thread
import time
import requests
import hashlib
import os
import re
import html2text
# Not needed due to inscriptis being way better.
#from urlextract import URLExtract
from inscriptis import get_text

# Hmm Polymorphism datastore, thread, etc
class perform_site_check(Thread):
    def __init__(self, *args, uuid=False, datastore, **kwargs):
        super().__init__(*args, **kwargs)
        self.timestamp = int(time.time())  # used for storage etc too
        self.uuid = uuid
        self.datastore = datastore
        self.url = datastore.get_val(uuid, 'url')
        self.current_md5 = datastore.get_val(uuid, 'previous_md5')
        self.output_path = "/datastore/{}".format(self.uuid)

    def save_firefox_screenshot(self, uuid, output):
        # @todo call selenium or whatever
        return

    def ensure_output_path(self):

        try:
            os.stat(self.output_path)
        except:
            os.mkdir(self.output_path)

    def save_response_html_output(self, output):
        # @todo maybe record a history.json, [timestamp, md5, filename]
        with open("{}/{}.txt".format(self.output_path, self.timestamp), 'w') as f:
            f.write(output)
            f.close()

    def save_response_stripped_output(self, output):
        fname = "{}/{}.stripped.txt".format(self.output_path, self.timestamp)
        with open(fname, 'w') as f:
            f.write(output)
            f.close()

        return fname

    def run(self):

        extra_headers = self.datastore.get_val(self.uuid, 'headers')

        # Tweak the base config with the per-watch ones
        request_headers = self.datastore.data['settings']['headers'].copy()
        request_headers.update(extra_headers)

        print("Checking", self.url)
        #print(request_headers)

        self.ensure_output_path()

        try:
            timeout = self.datastore.data['settings']['requests']['timeout']
        except KeyError:
            # @todo yeah this should go back to the default value in store.py, but this whole object should abstract off it
            timeout = 15

        try:
            r = requests.get(self.url,
                             headers=request_headers,
                             timeout=timeout,
                             verify=False)

            stripped_text_from_html = get_text(r.text)


            # @todo This should be a config option.
            # Many websites include junk in the links, trackers, etc.. Since we are really a service all about text changes..

# inscriptis handles this much cleaner, probably not needed..
#            extractor = URLExtract()
#            urls = extractor.find_urls(stripped_text_from_html)
            # Remove the urls, longest first so that we dont end up chewing up bigger links with parts of smaller ones.
#            if urls:
#                urls.sort(key=len, reverse=True)
#                for url in urls:
#                    # Sometimes URLExtract will consider something like 'foobar.com' as a link when that was just text.
#                    if "://" in url:
#                        # print ("Stripping link", url)
#                        stripped_text_from_html = stripped_text_from_html.replace(url, '')



        # Usually from networkIO/requests level
        except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout) as e:
            self.datastore.update_watch(self.uuid, 'last_error', str(e))
            print(str(e))

        except requests.exceptions.MissingSchema:
            print("Skipping {} due to missing schema/bad url".format(self.uuid))

        # Usually from html2text level
        except UnicodeDecodeError as e:
            self.datastore.update_watch(self.uuid, 'last_error', str(e))
            print(str(e))
            # figure out how to deal with this cleaner..
            # 'utf-8' codec can't decode byte 0xe9 in position 480: invalid continuation byte

        else:

            # We rely on the actual text in the html output.. many sites have random script vars etc
            self.datastore.update_watch(self.uuid, 'last_error', False)
            self.datastore.update_watch(self.uuid, 'last_check_status', r.status_code)

            fetched_md5 = hashlib.md5(stripped_text_from_html.encode('utf-8')).hexdigest()

            if self.current_md5 != fetched_md5:

                # Dont confuse people by putting last-changed, when it actually just changed from nothing..
                if self.datastore.get_val(self.uuid, 'previous_md5') is not None:
                    self.datastore.update_watch(self.uuid, 'last_changed', self.timestamp)

                self.datastore.update_watch(self.uuid, 'previous_md5', fetched_md5)
                self.save_response_html_output(r.text)
                output_filepath = self.save_response_stripped_output(stripped_text_from_html)

                # Update history with the stripped text for future reference, this will also mean we save the first
                # attempt because 'self.current_md5 != fetched_md5'  (current_md5 will be None when not run)
                # need to learn more about attr/setters/getters
                history = self.datastore.get_val(self.uuid, 'history')
                history.update(dict([(self.timestamp, output_filepath)]))
                self.datastore.update_watch(self.uuid, 'history', history)

        self.datastore.update_watch(self.uuid, 'last_checked', int(time.time()))
        pass
