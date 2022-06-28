import os
import uuid as uuid_builder

minimum_seconds_recheck_time = int(os.getenv('MINIMUM_SECONDS_RECHECK_TIME', 60))

from changedetectionio.notification import (
    default_notification_body,
    default_notification_format,
    default_notification_title,
)


class model(dict):
    __newest_history_key = None
    __history_n=0
    __base_config = {
            'url': None,
            'tag': None,
            'last_checked': 0,
            'last_changed': 0,
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
            'notification_title': default_notification_title,
            'notification_body': default_notification_body,
            'notification_format': default_notification_format,
            'css_filter': '',
            'extract_text': [],  # Extract text by regex after filters
            'subtractive_selectors': [],
            'trigger_text': [],  # List of text or regex to wait for until a change is detected
            'text_should_not_be_present': [], # Text that should not present
            'fetch_backend': None,
            'extract_title_as_title': False,
            'check_unique_lines': False, # On change-detected, compare against all history if its something new
            'proxy': None, # Preferred proxy connection
            # Re #110, so then if this is set to None, we know to use the default value instead
            # Requires setting to None on submit if it's the same as the default
            # Should be all None by default, so we use the system default in this case.
            'time_between_check': {'weeks': None, 'days': None, 'hours': None, 'minutes': None, 'seconds': None},
            'webdriver_delay': None
        }
    jitter_seconds = 0
    mtable = {'seconds': 1, 'minutes': 60, 'hours': 3600, 'days': 86400, 'weeks': 86400 * 7}
    def __init__(self, *arg, **kw):
        import uuid
        self.update(self.__base_config)
        self.__datastore_path = kw['datastore_path']

        self['uuid'] = str(uuid.uuid4())

        del kw['datastore_path']

        if kw.get('default'):
            self.update(kw['default'])
            del kw['default']

        # goes at the end so we update the default object with the initialiser
        super(model, self).__init__(*arg, **kw)

    @property
    def viewed(self):
        if int(self['last_viewed']) >= int(self.newest_history_key) :
            return True

        return False

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
        from os import mkdir, path, unlink
        import logging

        output_path = "{}/{}".format(self.__datastore_path, self['uuid'])

        # Incase the operator deleted it, check and create.
        if not os.path.isdir(output_path):
            mkdir(output_path)

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
        for m, n in self.mtable.items():
            x = self.get('time_between_check', {}).get(m, None)
            if x:
                seconds += x * n
        return seconds

    # Iterate over all history texts and see if something new exists
    def lines_contain_something_unique_compared_to_history(self, lines=[]):
        local_lines = [l.decode('utf-8').strip().lower() for l in lines]

        # Compare each lines (set) against each history text file (set) looking for something new..
        for k, v in self.history.items():
            alist = [line.decode('utf-8').strip().lower() for line in open(v, 'rb')]
            res = set(alist) != set(local_lines)
            if res:
                return True

        return False
