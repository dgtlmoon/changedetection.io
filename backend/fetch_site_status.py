import time
import requests
import hashlib
import os
import re
from inscriptis import get_text

from copy import deepcopy


# Some common stuff here that can be moved to a base class
class perform_site_check():

    def __init__(self, *args, datastore, **kwargs):
        super().__init__(*args, **kwargs)
        self.datastore = datastore

    def save_firefox_screenshot(self, uuid, output):
        # @todo call selenium or whatever
        return

    def ensure_output_path(self):

        try:
            os.stat(self.output_path)
        except:
            os.mkdir(self.output_path)

    def save_response_stripped_output(self, output, fname):

        with open(fname, 'w') as f:
            f.write(output)
            f.close()

        return fname

    def run(self, uuid):

        timestamp = int(time.time())  # used for storage etc too

        update_obj = {'previous_md5': self.datastore.data['watching'][uuid]['previous_md5'],
                      'history': {},
                      "last_checked": timestamp
                      }

        self.output_path = "/datastore/{}".format(uuid)
        self.ensure_output_path()

        extra_headers = self.datastore.get_val(uuid, 'headers')

        # Tweak the base config with the per-watch ones
        request_headers = self.datastore.data['settings']['headers']
        request_headers.update(extra_headers)

        # https://github.com/psf/requests/issues/4525
        # Requests doesnt yet support brotli encoding, so don't put 'br' here, be totally sure that the user cannot
        # do this by accident.
        if 'Accept-Encoding' in request_headers and "br" in request_headers['Accept-Encoding']:
            request_headers['Accept-Encoding'] = request_headers['Accept-Encoding'].replace(', br', '')

        try:
            timeout = self.datastore.data['settings']['requests']['timeout']
        except KeyError:
            # @todo yeah this should go back to the default value in store.py, but this whole object should abstract off it
            timeout = 15

        try:
            r = requests.get(self.datastore.get_val(uuid, 'url'),
                             headers=request_headers,
                             timeout=timeout,
                             verify=False)

            stripped_text_from_html = get_text(r.text)



        # Usually from networkIO/requests level
        except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout) as e:
            update_obj["last_error"] = str(e)

            print(str(e))

        except requests.exceptions.MissingSchema:
            print("Skipping {} due to missing schema/bad url".format(uuid))

        # Usually from html2text level
        except UnicodeDecodeError as e:

            update_obj["last_error"] = str(e)
            print(str(e))
            # figure out how to deal with this cleaner..
            # 'utf-8' codec can't decode byte 0xe9 in position 480: invalid continuation byte

        else:
            # We rely on the actual text in the html output.. many sites have random script vars etc,
            # in the future we'll implement other mechanisms.

            update_obj["last_check_status"] = r.status_code
            update_obj["last_error"] = False

            if not len(r.text):
                update_obj["last_error"] = "Empty reply"

            fetched_md5 = hashlib.md5(stripped_text_from_html.encode('utf-8')).hexdigest()

            # could be None or False depending on JSON type
            if self.datastore.data['watching'][uuid]['previous_md5'] != fetched_md5:

                # Don't confuse people by updating as last-changed, when it actually just changed from None..
                if self.datastore.get_val(uuid, 'previous_md5'):
                    update_obj["last_changed"] = timestamp

                update_obj["previous_md5"] = fetched_md5
                fname = "{}/{}.stripped.txt".format(self.output_path, fetched_md5)
                with open(fname, 'w') as f:
                    f.write(stripped_text_from_html)
                    f.close()

                # Update history with the stripped text for future reference, this will also mean we save the first
                # Should always be keyed by string(timestamp)
                update_obj.update({"history": {str(timestamp): fname}})

        return update_obj
