import time
import requests
import hashlib
from inscriptis import get_text
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Some common stuff here that can be moved to a base class
class perform_site_check():

    def __init__(self, *args, datastore, **kwargs):
        super().__init__(*args, **kwargs)
        self.datastore = datastore

    def strip_ignore_text(self, content, list_ignore_text):
        ignore = []
        for k in list_ignore_text:
            ignore.append(k.encode('utf8'))

        output = []
        for line in content.splitlines():
            line = line.encode('utf8')

            # Always ignore blank lines in this mode. (when this function gets called)
            if len(line.strip()):
                if not any(skip_text in line for skip_text in ignore):
                    output.append(line)

        return "\n".encode('utf8').join(output)



    def run(self, uuid):
        timestamp = int(time.time())  # used for storage etc too
        stripped_text_from_html = False
        changed_detected = False

        update_obj = {'previous_md5': self.datastore.data['watching'][uuid]['previous_md5'],
                      'history': {},
                      "last_checked": timestamp
                      }

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
            url = self.datastore.get_val(uuid, 'url')

            r = requests.get(url,
                             headers=request_headers,
                             timeout=timeout,
                             verify=False)

            # CSS Filter
            css_filter = self.datastore.data['watching'][uuid]['css_filter']
            if css_filter and len(css_filter.strip()):
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(r.content, "html.parser")
                stripped_text_from_html = ""
                for item in soup.select(css_filter):
                    text = str(item.get_text()).strip() + '\n'
                    stripped_text_from_html += text

            else:
                stripped_text_from_html = get_text(r.text)

        # Usually from networkIO/requests level
        except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout) as e:
            update_obj["last_error"] = str(e)
            print(str(e))

        except requests.exceptions.MissingSchema:
            print("Skipping {} due to missing schema/bad url".format(uuid))

        # Usually from html2text level
        except Exception as e:
            #        except UnicodeDecodeError as e:
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

            # If there's text to skip
            # @todo we could abstract out the get_text() to handle this cleaner
            if len(self.datastore.data['watching'][uuid]['ignore_text']):
                content = self.strip_ignore_text(stripped_text_from_html,
                                                 self.datastore.data['watching'][uuid]['ignore_text'])
            else:
                content = stripped_text_from_html.encode('utf8')

            fetched_md5 = hashlib.md5(content).hexdigest()

            # could be None or False depending on JSON type
            if self.datastore.data['watching'][uuid]['previous_md5'] != fetched_md5:
                changed_detected = True

                # Don't confuse people by updating as last-changed, when it actually just changed from None..
                if self.datastore.get_val(uuid, 'previous_md5'):
                    update_obj["last_changed"] = timestamp

                update_obj["previous_md5"] = fetched_md5

        return changed_detected, update_obj, stripped_text_from_html
