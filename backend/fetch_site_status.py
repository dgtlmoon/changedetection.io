import time
import requests
import hashlib
from inscriptis import get_text
import urllib3
from . import html_tools

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# Some common stuff here that can be moved to a base class
class perform_site_check():

    def __init__(self, *args, datastore, **kwargs):
        super().__init__(*args, **kwargs)
        self.datastore = datastore

    def strip_ignore_text(self, content, list_ignore_text):
        import re
        ignore = []
        ignore_regex = []
        for k in list_ignore_text:

            # Is it a regex?
            if k[0] == '/':
                ignore_regex.append(k.strip(" /"))
            else:
                ignore.append(k)

        output = []
        for line in content.splitlines():

            # Always ignore blank lines in this mode. (when this function gets called)
            if len(line.strip()):
                regex_matches = False

                # if any of these match, skip
                for regex in ignore_regex:
                    try:
                        if re.search(regex, line, re.IGNORECASE):
                            regex_matches = True
                    except Exception as e:
                        continue

                if not regex_matches and not any(skip_text in line for skip_text in ignore):
                    output.append(line.encode('utf8'))

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

            html = r.text

            # CSS Filter, extract the HTML that matches and feed that into the existing inscriptis::get_text
            css_filter_rule = self.datastore.data['watching'][uuid]['css_filter']
            if css_filter_rule and len(css_filter_rule.strip()):
                html = html_tools.css_filter(css_filter=css_filter_rule, html_content=r.content)

            stripped_text_from_html = get_text(html)

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

            # Extract title as title
            if self.datastore.data['settings']['application']['extract_title_as_title']:
                if not self.datastore.data['watching'][uuid]['title'] or not len(self.datastore.data['watching'][uuid]['title']):
                    update_obj['title'] = html_tools.extract_element(find='title', html_content=html)


        return changed_detected, update_obj, stripped_text_from_html
