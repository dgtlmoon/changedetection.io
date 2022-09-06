import os
import uuid as uuid_builder
from distutils.util import strtobool

minimum_seconds_recheck_time = int(os.getenv('MINIMUM_SECONDS_RECHECK_TIME', 60))
mtable = {'seconds': 1, 'minutes': 60, 'hours': 3600, 'days': 86400, 'weeks': 86400 * 7}

from changedetectionio.notification import (
    default_notification_format_for_watch
)


class model(dict):
    __newest_history_key = None
    __history_n=0
    __base_config = {
            'url': None,
            'tag': None,
            'last_checked': 0,
            'paused': False,
            'last_viewed': 0,  # history key value of the last viewed via the [diff] link
            #'newest_history_key': 0,
            'title': None,
            'previous_md5': False,
            'uuid': str(uuid_builder.uuid4()),
            'headers': {},  # Extra headers to send
            'body': None,
            'method': 'GET',
            #'history': {},  # Dict of timestamp and output stripped filename
            'ignore_text': [],  # List of text to ignore when calculating the comparison checksum
            # Custom notification content
            'notification_urls': [],  # List of URLs to add to the notification Queue (Usually AppRise)
            'notification_title': None,
            'notification_body': None,
            'notification_format': default_notification_format_for_watch,
            'notification_muted': False,
            'css_filter': '',
            'last_error': False,
            'extract_text': [],  # Extract text by regex after filters
            'subtractive_selectors': [],
            'trigger_text': [],  # List of text or regex to wait for until a change is detected
            'text_should_not_be_present': [], # Text that should not present
            'fetch_backend': None,
            'filter_failure_notification_send': strtobool(os.getenv('FILTER_FAILURE_NOTIFICATION_SEND_DEFAULT', 'True')),
            'consecutive_filter_failures': 0, # Every time the CSS/xPath filter cannot be located, reset when all is fine.
            'extract_title_as_title': False,
            'check_unique_lines': False, # On change-detected, compare against all history if its something new
            'proxy': None, # Preferred proxy connection
            # Re #110, so then if this is set to None, we know to use the default value instead
            # Requires setting to None on submit if it's the same as the default
            # Should be all None by default, so we use the system default in this case.
            'time_between_check': {'weeks': None, 'days': None, 'hours': None, 'minutes': None, 'seconds': None},
            'webdriver_delay': None,
            'webdriver_js_execute_code': None, # Run before change-detection
        }
    jitter_seconds = 0

    def __init__(self, *arg, **kw):

        self.update(self.__base_config)
        self.__datastore_path = kw['datastore_path']

        self['uuid'] = str(uuid_builder.uuid4())

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
        if int(self['last_viewed']) >= int(self.newest_history_key) :
            return True

        return False

    def ensure_data_dir_exists(self):
        target_path = os.path.join(self.__datastore_path, self['uuid'])
        if not os.path.isdir(target_path):
            print ("> Creating data dir {}".format(target_path))
            os.mkdir(target_path)

    @property
    def label(self):
        # Used for sorting
        if self['title']:
            return self['title']
        return self['url']

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
        tmp_history = {}
        import logging
        import time

        # Read the history file as a dict
        fname = os.path.join(self.__datastore_path, self.get('uuid'), "history.txt")
        if os.path.isfile(fname):
            logging.debug("Reading history index " + str(time.time()))
            with open(fname, "r") as f:
                tmp_history = dict(i.strip().split(',', 2) for i in f.readlines())

        if len(tmp_history):
            self.__newest_history_key = list(tmp_history.keys())[-1]

        self.__history_n = len(tmp_history)

        return tmp_history

    @property
    def has_history(self):
        fname = os.path.join(self.__datastore_path, self.get('uuid'), "history.txt")
        return os.path.isfile(fname)

    # Returns the newest key, but if theres only 1 record, then it's counted as not being new, so return 0.
    @property
    def newest_history_key(self):
        if self.__newest_history_key is not None:
            return self.__newest_history_key

        if len(self.history) <= 1:
            return 0


        bump = self.history
        return self.__newest_history_key

    # Save some text file to the appropriate path and bump the history
    # result_obj from fetch_site_status.run()
    def save_history_text(self, contents, timestamp):
        import uuid
        import logging

        output_path = "{}/{}".format(self.__datastore_path, self['uuid'])

        self.ensure_data_dir_exists()

        snapshot_fname = "{}/{}.stripped.txt".format(output_path, uuid.uuid4())
        logging.debug("Saving history text {}".format(snapshot_fname))

        with open(snapshot_fname, 'wb') as f:
            f.write(contents)
            f.close()

        # Append to index
        # @todo check last char was \n
        index_fname = "{}/history.txt".format(output_path)
        with open(index_fname, 'a') as f:
            f.write("{},{}\n".format(timestamp, snapshot_fname))
            f.close()

        self.__newest_history_key = timestamp
        self.__history_n+=1

        #@todo bump static cache of the last timestamp so we dont need to examine the file to set a proper ''viewed'' status
        return snapshot_fname

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
            alist = set([line.decode('utf-8').strip().lower() for line in open(v, 'rb')])
            existing_history = existing_history.union(alist)

        # Check that everything in local_lines(new stuff) already exists in existing_history - it should
        # if not, something new happened
        return not local_lines.issubset(existing_history)

    def get_screenshot(self):
        fname = os.path.join(self.__datastore_path, self['uuid'], "last-screenshot.png")
        if os.path.isfile(fname):
            return fname

        return False

    def __get_file_ctime(self, filename):
        fname = os.path.join(self.__datastore_path, self['uuid'], filename)
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

    def get_error_text(self):
        """Return the text saved from a previous request that resulted in a non-200 error"""
        fname = os.path.join(self.__datastore_path, self['uuid'], "last-error.txt")
        if os.path.isfile(fname):
            with open(fname, 'r') as f:
                return f.read()
        return False

    def get_error_snapshot(self):
        """Return path to the screenshot that resulted in a non-200 error"""
        fname = os.path.join(self.__datastore_path, self['uuid'], "last-error-screenshot.png")
        if os.path.isfile(fname):
            return fname
        return False
