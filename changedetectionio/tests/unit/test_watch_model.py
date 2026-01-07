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
        watch.save_history_blob(contents="hello world", timestamp=100, snapshot_id=str(uuid_builder.uuid4()))
        watch.save_history_blob(contents="hello world", timestamp=105, snapshot_id=str(uuid_builder.uuid4()))
        watch.save_history_blob(contents="hello world", timestamp=109, snapshot_id=str(uuid_builder.uuid4()))
        watch.save_history_blob(contents="hello world", timestamp=112, snapshot_id=str(uuid_builder.uuid4()))
        watch.save_history_blob(contents="hello world", timestamp=115, snapshot_id=str(uuid_builder.uuid4()))
        watch.save_history_blob(contents="hello world", timestamp=117, snapshot_id=str(uuid_builder.uuid4()))
    
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

        watch.save_history_blob(contents="hello world", timestamp=100, snapshot_id=str(uuid_builder.uuid4()))
        p = watch.get_from_version_based_on_last_viewed
        assert p == "100", "Correct with only one history snapshot"

        watch['last_viewed'] = 200
        p = watch.get_from_version_based_on_last_viewed
        assert p == "100", "Correct with only one history snapshot"

    def test_watch_link_property_with_link_to_open(self):
        """Test that link property uses link_to_open when set, otherwise falls back to URL"""
        watch = Watch.model(datastore_path='/tmp', default={'url': 'https://example.com/feed/rss'})
        
        # Test 1: When link_to_open is not set, should use URL
        assert watch.link == 'https://example.com/feed/rss'
        
        # Test 2: When link_to_open is set, should use it
        watch['link_to_open'] = 'https://example.com/blog/'
        assert watch.link == 'https://example.com/blog/'
        
        # Test 3: When link_to_open is empty string, should fall back to URL
        watch['link_to_open'] = ''
        assert watch.link == 'https://example.com/feed/rss'
        
        # Test 4: When link_to_open is None, should fall back to URL
        watch['link_to_open'] = None
        assert watch.link == 'https://example.com/feed/rss'
        
        # Test 5: When link_to_open has whitespace, should be trimmed and used
        watch['link_to_open'] = '  https://example.com/blog/  '
        assert watch.link == 'https://example.com/blog/'
        
        # Test 6: When link_to_open is invalid URL, should fall back to URL
        watch['link_to_open'] = 'not-a-valid-url'
        assert watch.link == 'https://example.com/feed/rss'
        
        # Test 7: When URL is invalid, link should return 'DISABLED'
        watch['url'] = 'invalid-url'
        watch['link_to_open'] = None
        assert watch.link == 'DISABLED'

if __name__ == '__main__':
    unittest.main()
