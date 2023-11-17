#!/usr/bin/python3

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_notification_diff

import unittest
import os

from changedetectionio.model import Watch

# mostly
class TestDiffBuilder(unittest.TestCase):

    def test_watch_module(self):
        import uuid as uuid_builder
        watch = Watch.model(datastore_path='/tmp', default={})
        watch.ensure_data_dir_exists()

        watch['last_viewed'] = 110

        watch.save_history_text(contents=b"hello world", timestamp=100, snapshot_id=str(uuid_builder.uuid4()))
        watch.save_history_text(contents=b"hello world", timestamp=105, snapshot_id=str(uuid_builder.uuid4()))
        watch.save_history_text(contents=b"hello world", timestamp=109, snapshot_id=str(uuid_builder.uuid4()))
        watch.save_history_text(contents=b"hello world", timestamp=112, snapshot_id=str(uuid_builder.uuid4()))
        watch.save_history_text(contents=b"hello world", timestamp=115, snapshot_id=str(uuid_builder.uuid4()))

        p = watch.get_next_snapshot_key_to_last_viewed
        assert p == "112", "Correct last-viewed timestamp was detected"

if __name__ == '__main__':
    unittest.main()
