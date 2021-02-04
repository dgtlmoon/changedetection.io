import time
import requests
import hashlib
import os
import re
from inscriptis import get_text

# Some common stuff here that can be moved to a base class
class perform_site_check():

    # New state that is set after a check
    # Return value dict
    update_obj = {}


    def __init__(self, *args, uuid=False, datastore, **kwargs):
        super().__init__(*args, **kwargs)
        self.timestamp = int(time.time())  # used for storage etc too
        self.uuid = uuid
        self.datastore = datastore
        self.url = datastore.get_val(uuid, 'url')
        self.current_md5 = datastore.get_val(uuid, 'previous_md5')
        self.output_path = "/datastore/{}".format(self.uuid)

        self.ensure_output_path()
        self.run()

    # Current state of what needs to be updated
    @property
    def update_data(self):
        return self.update_obj

    def save_firefox_screenshot(self, uuid, output):
        # @todo call selenium or whatever
        return

    def ensure_output_path(self):

        try:
            os.stat(self.output_path)
        except:
            os.mkdir(self.output_path)

    def save_response_html_output(self, output):

        # @todo Saving the original HTML can be very large, better to set as an option, these files could be important to some.
        with open("{}/{}.html".format(self.output_path, self.timestamp), 'w') as f:
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
            r = requests.get(self.url,
                             headers=request_headers,
                             timeout=timeout,
                             verify=False)

            stripped_text_from_html = get_text(r.text)



        # Usually from networkIO/requests level
        except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout) as e:
            self.update_obj["last_error"] = str(e)

            print(str(e))

        except requests.exceptions.MissingSchema:
            print("Skipping {} due to missing schema/bad url".format(self.uuid))

        # Usually from html2text level
        except UnicodeDecodeError as e:

            self.update_obj["last_error"] = str(e)
            print(str(e))
            # figure out how to deal with this cleaner..
            # 'utf-8' codec can't decode byte 0xe9 in position 480: invalid continuation byte

        else:
            # We rely on the actual text in the html output.. many sites have random script vars etc,
            # in the future we'll implement other mechanisms.

            self.update_obj["last_check_status"] = r.status_code
            self.update_obj["last_error"] = False

            fetched_md5 = hashlib.md5(stripped_text_from_html.encode('utf-8')).hexdigest()


            if self.current_md5 != fetched_md5: # could be None or False depending on JSON type

                # Don't confuse people by updating as last-changed, when it actually just changed from None..
                if self.datastore.get_val(self.uuid, 'previous_md5'):
                    self.update_obj["last_changed"] = self.timestamp

                self.update_obj["previous_md5"] = fetched_md5

                self.save_response_html_output(r.text)
                output_filepath = self.save_response_stripped_output(stripped_text_from_html)

                # Update history with the stripped text for future reference, this will also mean we save the first
                timestamp = str(self.timestamp)
                self.update_obj.update({"history": {timestamp: output_filepath}})

            self.update_obj["last_checked"] = self.timestamp

