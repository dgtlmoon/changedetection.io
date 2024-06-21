from changedetectionio.strtobool import strtobool
from changedetectionio.safe_jinja import render as jinja_render

import os
import re
import time
import uuid
from pathlib import Path
from loguru import logger

# Allowable protocols, protects against javascript: etc
# file:// is further checked by ALLOW_FILE_URI
SAFE_PROTOCOL_REGEX='^(http|https|ftp|file):'

minimum_seconds_recheck_time = int(os.getenv('MINIMUM_SECONDS_RECHECK_TIME', 3))
mtable = {'seconds': 1, 'minutes': 60, 'hours': 3600, 'days': 86400, 'weeks': 86400 * 7}

from changedetectionio.notification import (
    default_notification_format_for_watch
)

base_config = {
    'body': None,
    'browser_steps': [],
    'browser_steps_last_error_step': None,
    'check_unique_lines': False,  # On change-detected, compare against all history if its something new
    'check_count': 0,
    'date_created': None,
    'consecutive_filter_failures': 0,  # Every time the CSS/xPath filter cannot be located, reset when all is fine.
    'extract_text': [],  # Extract text by regex after filters
    'extract_title_as_title': False,
    'fetch_backend': 'system', # plaintext, playwright etc
    'fetch_time': 0.0,
    'processor': 'text_json_diff', # could be restock_diff or others from .processors
    'filter_failure_notification_send': strtobool(os.getenv('FILTER_FAILURE_NOTIFICATION_SEND_DEFAULT', 'True')),
    'filter_text_added': True,
    'filter_text_replaced': True,
    'filter_text_removed': True,
    'has_ldjson_price_data': None,
    'track_ldjson_price_data': None,
    'headers': {},  # Extra headers to send
    'ignore_text': [],  # List of text to ignore when calculating the comparison checksum
    'in_stock' : None,
    'in_stock_only' : True, # Only trigger change on going to instock from out-of-stock
    'include_filters': [],
    'last_checked': 0,
    'last_error': False,
    'last_viewed': 0,  # history key value of the last viewed via the [diff] link
    'method': 'GET',
    'notification_alert_count': 0,
    # Custom notification content
    'notification_body': None,
    'notification_format': default_notification_format_for_watch,
    'notification_muted': False,
    'notification_title': None,
    'notification_screenshot': False,  # Include the latest screenshot if available and supported by the apprise URL
    'notification_urls': [],  # List of URLs to add to the notification Queue (Usually AppRise)
    'paused': False,
    'previous_md5': False,
    'previous_md5_before_filters': False,  # Used for skipping changedetection entirely
    'proxy': None,  # Preferred proxy connection
    'remote_server_reply': None, # From 'server' reply header
    'sort_text_alphabetically': False,
    'subtractive_selectors': [],
    'tag': '', # Old system of text name for a tag, to be removed
    'tags': [], # list of UUIDs to App.Tags
    'text_should_not_be_present': [],  # Text that should not present
    # Re #110, so then if this is set to None, we know to use the default value instead
    # Requires setting to None on submit if it's the same as the default
    # Should be all None by default, so we use the system default in this case.
    'time_between_check': {'weeks': None, 'days': None, 'hours': None, 'minutes': None, 'seconds': None},
    'time_between_check_use_default': True,
    'title': None,
    'trigger_text': [],  # List of text or regex to wait for until a change is detected
    'url': '',
    'uuid': str(uuid.uuid4()),
    'webdriver_delay': None,
    'webdriver_js_execute_code': None,  # Run before change-detection
}


def is_safe_url(test_url):
    # See https://github.com/dgtlmoon/changedetection.io/issues/1358

    # Remove 'source:' prefix so we dont get 'source:javascript:' etc
    # 'source:' is a valid way to tell us to return the source

    r = re.compile(re.escape('source:'), re.IGNORECASE)
    test_url = r.sub('', test_url)

    pattern = re.compile(os.getenv('SAFE_PROTOCOL_REGEX', SAFE_PROTOCOL_REGEX), re.IGNORECASE)
    if not pattern.match(test_url.strip()):
        return False

    return True

class model(dict):
    __newest_history_key = None
    __history_n = 0
    jitter_seconds = 0

    def __init__(self, *arg, **kw):

        self.update(base_config)
        self.__datastore_path = kw['datastore_path']

        self['uuid'] = str(uuid.uuid4())

        del kw['datastore_path']

        if kw.get('default'):
            self.update(kw['default'])
            del kw['default']

        # Be sure the cached timestamp is ready
        bump = self.history

        # Goes at the end so we update the default object with the initialiser
        super(model, self).__init__(*arg, **kw)

    @property
    def viewed(self):
        # Don't return viewed when last_viewed is 0 and newest_key is 0
        if int(self['last_viewed']) and int(self['last_viewed']) >= int(self.newest_history_key) :
            return True

        return False

    def ensure_data_dir_exists(self):
        if not os.path.isdir(self.watch_data_dir):
            logger.debug(f"> Creating data dir {self.watch_data_dir}")
            os.mkdir(self.watch_data_dir)

    @property
    def link(self):

        url = self.get('url', '')
        if not is_safe_url(url):
            return 'DISABLED'

        ready_url = url
        if '{%' in url or '{{' in url:
            # Jinja2 available in URLs along with https://pypi.org/project/jinja2-time/
            try:
                ready_url = jinja_render(template_str=url)
            except Exception as e:
                logger.critical(f"Invalid URL template for: '{url}' - {str(e)}")
                from flask import (
                    flash, Markup, url_for
                )
                message = Markup('<a href="{}#general">The URL {} is invalid and cannot be used, click to edit</a>'.format(
                    url_for('edit_page', uuid=self.get('uuid')), self.get('url', '')))
                flash(message, 'error')
                return ''

        if ready_url.startswith('source:'):
            ready_url=ready_url.replace('source:', '')
        return ready_url

    @property
    def is_source_type_url(self):
        return self.get('url', '').startswith('source:')

    @property
    def get_fetch_backend(self):
        """
        Like just using the `fetch_backend` key but there could be some logic
        :return:
        """
        # Maybe also if is_image etc?
        # This is because chrome/playwright wont render the PDF in the browser and we will just fetch it and use pdf2html to see the text.
        if self.is_pdf:
            return 'html_requests'

        return self.get('fetch_backend')

    @property
    def is_pdf(self):
        # content_type field is set in the future
        # https://github.com/dgtlmoon/changedetection.io/issues/1392
        # Not sure the best logic here
        return self.get('url', '').lower().endswith('.pdf') or 'pdf' in self.get('content_type', '').lower()

    @property
    def label(self):
        # Used for sorting
        return self.get('title') if self.get('title') else self.get('url')

    @property
    def last_changed(self):
        # last_changed will be the newest snapshot, but when we have just one snapshot, it should be 0
        if self.__history_n <= 1:
            return 0
        if self.__newest_history_key:
            return int(self.__newest_history_key)
        return 0

    @property
    def history_n(self):
        return self.__history_n

    @property
    def history(self):
        """History index is just a text file as a list
            {watch-uuid}/history.txt

            contains a list like

            {epoch-time},{filename}\n

            We read in this list as the history information

        """
        tmp_history = {}

        # Read the history file as a dict
        fname = os.path.join(self.watch_data_dir, "history.txt")
        if os.path.isfile(fname):
            logger.debug(f"Reading watch history index for {self.get('uuid')}")
            with open(fname, "r") as f:
                for i in f.readlines():
                    if ',' in i:
                        k, v = i.strip().split(',', 2)

                        # The index history could contain a relative path, so we need to make the fullpath
                        # so that python can read it
                        if not '/' in v and not '\'' in v:
                            v = os.path.join(self.watch_data_dir, v)
                        else:
                            # It's possible that they moved the datadir on older versions
                            # So the snapshot exists but is in a different path
                            snapshot_fname = v.split('/')[-1]
                            proposed_new_path = os.path.join(self.watch_data_dir, snapshot_fname)
                            if not os.path.exists(v) and os.path.exists(proposed_new_path):
                                v = proposed_new_path

                        tmp_history[k] = v

        if len(tmp_history):
            self.__newest_history_key = list(tmp_history.keys())[-1]

        self.__history_n = len(tmp_history)

        return tmp_history

    @property
    def has_history(self):
        fname = os.path.join(self.watch_data_dir, "history.txt")
        return os.path.isfile(fname)

    @property
    def has_browser_steps(self):
        has_browser_steps = self.get('browser_steps') and list(filter(
            lambda s: (s['operation'] and len(s['operation']) and s['operation'] != 'Choose one' and s['operation'] != 'Goto site'),
            self.get('browser_steps')))

        return has_browser_steps

    # Returns the newest key, but if theres only 1 record, then it's counted as not being new, so return 0.
    @property
    def newest_history_key(self):
        if self.__newest_history_key is not None:
            return self.__newest_history_key

        if len(self.history) <= 1:
            return 0


        bump = self.history
        return self.__newest_history_key

    # Given an arbitrary timestamp, find the closest next key
    # For example, last_viewed = 1000 so it should return the next 1001 timestamp
    #
    # used for the [diff] button so it can preset a smarter from_version
    @property
    def get_next_snapshot_key_to_last_viewed(self):

        """Unfortunately for now timestamp is stored as string key"""
        keys = list(self.history.keys())
        if not keys:
            return None

        last_viewed = int(self.get('last_viewed'))
        prev_k = keys[0]
        sorted_keys = sorted(keys, key=lambda x: int(x))
        sorted_keys.reverse()

        # When the 'last viewed' timestamp is greater than the newest snapshot, return second last
        if last_viewed > int(sorted_keys[0]):
            return sorted_keys[1]

        for k in sorted_keys:
            if int(k) < last_viewed:
                if prev_k == sorted_keys[0]:
                    # Return the second last one so we dont recommend the same version compares itself
                    return sorted_keys[1]

                return prev_k
            prev_k = k

        return keys[0]

    def get_history_snapshot(self, timestamp):
        import brotli
        filepath = self.history[timestamp]

        # See if a brotli versions exists and switch to that
        if not filepath.endswith('.br') and os.path.isfile(f"{filepath}.br"):
            filepath = f"{filepath}.br"

        # OR in the backup case that the .br does not exist, but the plain one does
        if filepath.endswith('.br') and not os.path.isfile(filepath):
            if os.path.isfile(filepath.replace('.br', '')):
                filepath = filepath.replace('.br', '')

        if filepath.endswith('.br'):
            # Brotli doesnt have a fileheader to detect it, so we rely on filename
            # https://www.rfc-editor.org/rfc/rfc7932
            with open(filepath, 'rb') as f:
                return(brotli.decompress(f.read()).decode('utf-8'))

        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()

    # Save some text file to the appropriate path and bump the history
    # result_obj from fetch_site_status.run()
    def save_history_text(self, contents, timestamp, snapshot_id):
        import brotli

        logger.trace(f"{self.get('uuid')} - Updating history.txt with timestamp {timestamp}")

        self.ensure_data_dir_exists()

        threshold = int(os.getenv('SNAPSHOT_BROTLI_COMPRESSION_THRESHOLD', 1024))
        skip_brotli = strtobool(os.getenv('DISABLE_BROTLI_TEXT_SNAPSHOT', 'False'))

        if not skip_brotli and len(contents) > threshold:
            snapshot_fname = f"{snapshot_id}.txt.br"
            dest = os.path.join(self.watch_data_dir, snapshot_fname)
            if not os.path.exists(dest):
                with open(dest, 'wb') as f:
                    f.write(brotli.compress(contents, mode=brotli.MODE_TEXT))
        else:
            snapshot_fname = f"{snapshot_id}.txt"
            dest = os.path.join(self.watch_data_dir, snapshot_fname)
            if not os.path.exists(dest):
                with open(dest, 'wb') as f:
                    f.write(contents)

        # Append to index
        # @todo check last char was \n
        index_fname = os.path.join(self.watch_data_dir, "history.txt")
        with open(index_fname, 'a') as f:
            f.write("{},{}\n".format(timestamp, snapshot_fname))
            f.close()

        self.__newest_history_key = timestamp
        self.__history_n += 1

        # @todo bump static cache of the last timestamp so we dont need to examine the file to set a proper ''viewed'' status
        return snapshot_fname

    @property
    @property
    def has_empty_checktime(self):
        # using all() + dictionary comprehension
        # Check if all values are 0 in dictionary
        res = all(x == None or x == False or x==0 for x in self.get('time_between_check', {}).values())
        return res

    def threshold_seconds(self):
        seconds = 0
        for m, n in mtable.items():
            x = self.get('time_between_check', {}).get(m, None)
            if x:
                seconds += x * n
        return seconds

    # Iterate over all history texts and see if something new exists
    def lines_contain_something_unique_compared_to_history(self, lines: list):
        local_lines = set([l.decode('utf-8').strip().lower() for l in lines])

        # Compare each lines (set) against each history text file (set) looking for something new..
        existing_history = set({})
        for k, v in self.history.items():
            content = self.get_history_snapshot(k)
            alist = set([line.strip().lower() for line in content.splitlines()])
            existing_history = existing_history.union(alist)

        # Check that everything in local_lines(new stuff) already exists in existing_history - it should
        # if not, something new happened
        return not local_lines.issubset(existing_history)

    def get_screenshot(self):
        fname = os.path.join(self.watch_data_dir, "last-screenshot.png")
        if os.path.isfile(fname):
            return fname

        # False is not an option for AppRise, must be type None
        return None

    def __get_file_ctime(self, filename):
        fname = os.path.join(self.watch_data_dir, filename)
        if os.path.isfile(fname):
            return int(os.path.getmtime(fname))
        return False

    @property
    def error_text_ctime(self):
        return self.__get_file_ctime('last-error.txt')

    @property
    def snapshot_text_ctime(self):
        if self.history_n==0:
            return False

        timestamp = list(self.history.keys())[-1]
        return int(timestamp)

    @property
    def snapshot_screenshot_ctime(self):
        return self.__get_file_ctime('last-screenshot.png')

    @property
    def snapshot_error_screenshot_ctime(self):
        return self.__get_file_ctime('last-error-screenshot.png')

    @property
    def watch_data_dir(self):
        # The base dir of the watch data
        return os.path.join(self.__datastore_path, self['uuid'])
    
    def get_error_text(self):
        """Return the text saved from a previous request that resulted in a non-200 error"""
        fname = os.path.join(self.watch_data_dir, "last-error.txt")
        if os.path.isfile(fname):
            with open(fname, 'r') as f:
                return f.read()
        return False

    def get_error_snapshot(self):
        """Return path to the screenshot that resulted in a non-200 error"""
        fname = os.path.join(self.watch_data_dir, "last-error-screenshot.png")
        if os.path.isfile(fname):
            return fname
        return False


    def pause(self):
        self['paused'] = True

    def unpause(self):
        self['paused'] = False

    def toggle_pause(self):
        self['paused'] ^= True

    def mute(self):
        self['notification_muted'] = True

    def unmute(self):
        self['notification_muted'] = False

    def toggle_mute(self):
        self['notification_muted'] ^= True

    def extract_regex_from_all_history(self, regex):
        import csv
        import re
        import datetime
        csv_output_filename = False
        csv_writer = False
        f = None

        # self.history will be keyed with the full path
        for k, fname in self.history.items():
            if os.path.isfile(fname):
                if True:
                    contents = self.get_history_snapshot(k)
                    res = re.findall(regex, contents, re.MULTILINE)
                    if res:
                        if not csv_writer:
                            # A file on the disk can be transferred much faster via flask than a string reply
                            csv_output_filename = 'report.csv'
                            f = open(os.path.join(self.watch_data_dir, csv_output_filename), 'w')
                            # @todo some headers in the future
                            #fieldnames = ['Epoch seconds', 'Date']
                            csv_writer = csv.writer(f,
                                                    delimiter=',',
                                                    quotechar='"',
                                                    quoting=csv.QUOTE_MINIMAL,
                                                    #fieldnames=fieldnames
                                                    )
                            csv_writer.writerow(['Epoch seconds', 'Date'])
                            # csv_writer.writeheader()

                        date_str = datetime.datetime.fromtimestamp(int(k)).strftime('%Y-%m-%d %H:%M:%S')
                        for r in res:
                            row = [k, date_str]
                            if isinstance(r, str):
                                row.append(r)
                            else:
                                row+=r
                            csv_writer.writerow(row)

        if f:
            f.close()

        return csv_output_filename


    def has_special_diff_filter_options_set(self):

        # All False - nothing would be done, so act like it's not processable
        if not self.get('filter_text_added', True) and not self.get('filter_text_replaced', True) and not self.get('filter_text_removed', True):
            return False

        # Or one is set
        if not self.get('filter_text_added', True) or not self.get('filter_text_replaced', True) or not self.get('filter_text_removed', True):
            return True

        # None is set
        return False

    def save_error_text(self, contents):
        self.ensure_data_dir_exists()
        target_path = os.path.join(self.watch_data_dir, "last-error.txt")
        with open(target_path, 'w') as f:
            f.write(contents)

    def save_xpath_data(self, data, as_error=False):
        import json

        if as_error:
            target_path = os.path.join(self.watch_data_dir, "elements-error.json")
        else:
            target_path = os.path.join(self.watch_data_dir, "elements.json")

        self.ensure_data_dir_exists()

        with open(target_path, 'w') as f:
            f.write(json.dumps(data))
            f.close()

    # Save as PNG, PNG is larger but better for doing visual diff in the future
    def save_screenshot(self, screenshot: bytes, as_error=False):

        if as_error:
            target_path = os.path.join(self.watch_data_dir, "last-error-screenshot.png")
        else:
            target_path = os.path.join(self.watch_data_dir, "last-screenshot.png")

        self.ensure_data_dir_exists()

        with open(target_path, 'wb') as f:
            f.write(screenshot)
            f.close()


    def get_last_fetched_text_before_filters(self):
        import brotli
        filepath = os.path.join(self.watch_data_dir, 'last-fetched.br')

        if not os.path.isfile(filepath):
            # If a previous attempt doesnt yet exist, just snarf the previous snapshot instead
            dates = list(self.history.keys())
            if len(dates):
                return self.get_history_snapshot(dates[-1])
            else:
                return ''

        with open(filepath, 'rb') as f:
            return(brotli.decompress(f.read()).decode('utf-8'))

    def save_last_text_fetched_before_filters(self, contents):
        import brotli
        filepath = os.path.join(self.watch_data_dir, 'last-fetched.br')
        with open(filepath, 'wb') as f:
            f.write(brotli.compress(contents, mode=brotli.MODE_TEXT))

    def save_last_fetched_html(self, timestamp, contents):
        import brotli

        self.ensure_data_dir_exists()
        snapshot_fname = f"{timestamp}.html.br"
        filepath = os.path.join(self.watch_data_dir, snapshot_fname)

        with open(filepath, 'wb') as f:
            contents = contents.encode('utf-8') if isinstance(contents, str) else contents
            try:
                f.write(brotli.compress(contents))
            except Exception as e:
                logger.warning(f"{self.get('uuid')} - Unable to compress snapshot, saving as raw data to {filepath}")
                logger.warning(e)
                f.write(contents)

        self._prune_last_fetched_html_snapshots()

    def get_fetched_html(self, timestamp):
        import brotli

        snapshot_fname = f"{timestamp}.html.br"
        filepath = os.path.join(self.watch_data_dir, snapshot_fname)
        if os.path.isfile(filepath):
            with open(filepath, 'rb') as f:
                return (brotli.decompress(f.read()).decode('utf-8'))

        return False


    def _prune_last_fetched_html_snapshots(self):

        dates = list(self.history.keys())
        dates.reverse()

        for index, timestamp in enumerate(dates):
            snapshot_fname = f"{timestamp}.html.br"
            filepath = os.path.join(self.watch_data_dir, snapshot_fname)

            # Keep only the first 2
            if index > 1 and os.path.isfile(filepath):
                os.remove(filepath)


    @property
    def get_browsersteps_available_screenshots(self):
        "For knowing which screenshots are available to show the user in BrowserSteps UI"
        available = []
        for f in Path(self.watch_data_dir).glob('step_before-*.jpeg'):
            step_n=re.search(r'step_before-(\d+)', f.name)
            if step_n:
                available.append(step_n.group(1))
        return available
