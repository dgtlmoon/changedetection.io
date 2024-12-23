#!/usr/bin/env python3

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_notification_diff

import unittest
import os

from changedetectionio.model import Watch

# mostly
class TestDiffBuilder(unittest.TestCase):

    def test_watch_get_suggested_from_diff_timestamp(self):
        import uuid as uuid_builder
        watch = Watch.model(datastore_path='/tmp', default={})
        watch.ensure_data_dir_exists()


        # Contents from the browser are always returned from the browser/requests/etc as str, str is basically UTF-16 in python
        watch.save_history_text(contents="hello world", timestamp=100, snapshot_id=str(uuid_builder.uuid4()))
        watch.save_history_text(contents="hello world", timestamp=105, snapshot_id=str(uuid_builder.uuid4()))
        watch.save_history_text(contents="hello world", timestamp=109, snapshot_id=str(uuid_builder.uuid4()))
        watch.save_history_text(contents="hello world", timestamp=112, snapshot_id=str(uuid_builder.uuid4()))
        watch.save_history_text(contents="hello world", timestamp=115, snapshot_id=str(uuid_builder.uuid4()))
        watch.save_history_text(contents="hello world", timestamp=117, snapshot_id=str(uuid_builder.uuid4()))
    
        p = watch.get_from_version_based_on_last_viewed
        assert p == "100", "Correct 'last viewed' timestamp was detected"

        watch['last_viewed'] = 110
        p = watch.get_from_version_based_on_last_viewed
        assert p == "109", "Correct 'last viewed' timestamp was detected"

        watch['last_viewed'] = 116
        p = watch.get_from_version_based_on_last_viewed
        assert p == "115", "Correct 'last viewed' timestamp was detected"

        watch['last_viewed'] = 99
        p = watch.get_from_version_based_on_last_viewed
        assert p == "100", "When the 'last viewed' timestamp is less than the oldest snapshot, return oldest"

        watch['last_viewed'] = 200
        p = watch.get_from_version_based_on_last_viewed
        assert p == "115", "When the 'last viewed' timestamp is greater than the newest snapshot, return second newest"

        watch['last_viewed'] = 109
        p = watch.get_from_version_based_on_last_viewed
        assert p == "109", "Correct when its the same time"

        # new empty one
        watch = Watch.model(datastore_path='/tmp', default={})
        p = watch.get_from_version_based_on_last_viewed
        assert p == None, "None when no history available"

        watch.save_history_text(contents="hello world", timestamp=100, snapshot_id=str(uuid_builder.uuid4()))
        p = watch.get_from_version_based_on_last_viewed
        assert p == "100", "Correct with only one history snapshot"

        watch['last_viewed'] = 200
        p = watch.get_from_version_based_on_last_viewed
        assert p == "100", "Correct with only one history snapshot"

if __name__ == '__main__':
    unittest.main()
