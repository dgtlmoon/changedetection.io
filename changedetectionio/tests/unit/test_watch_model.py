#!/usr/bin/env python3

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_notification_diff

import unittest
import os
import pickle
from copy import deepcopy

from changedetectionio.model import Watch, Tag

# mostly
class TestDiffBuilder(unittest.TestCase):

    def test_watch_get_suggested_from_diff_timestamp(self):
        import uuid as uuid_builder
        # Create minimal mock datastore for tests
        mock_datastore = {
            'settings': {
                'application': {}
            },
            'watching': {}
        }
        watch = Watch.model(datastore_path='/tmp', __datastore=mock_datastore, default={})
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
        watch = Watch.model(datastore_path='/tmp', __datastore=mock_datastore, default={})
        p = watch.get_from_version_based_on_last_viewed
        assert p == None, "None when no history available"

        watch.save_history_blob(contents="hello world", timestamp=100, snapshot_id=str(uuid_builder.uuid4()))
        p = watch.get_from_version_based_on_last_viewed
        assert p == "100", "Correct with only one history snapshot"

        watch['last_viewed'] = 200
        p = watch.get_from_version_based_on_last_viewed
        assert p == "100", "Correct with only one history snapshot"

    def test_watch_deepcopy_doesnt_copy_datastore(self):
        """
        CRITICAL: Ensure deepcopy(watch) shares __datastore instead of copying it.

        Without this, deepcopy causes exponential memory growth:
        - 100 watches × deepcopy each = 10,000 watch objects in memory (100²)
        - Memory grows from 120MB → 2GB

        This test prevents regressions in the __deepcopy__ implementation.
        """
        # Create mock datastore with multiple watches
        mock_datastore = {
            'settings': {'application': {'history_snapshot_max_length': 10}},
            'watching': {}
        }

        # Create 3 watches that all reference the same datastore
        watches = []
        for i in range(3):
            watch = Watch.model(
                __datastore=mock_datastore,
                datastore_path='/tmp/test',
                default={'url': f'https://example{i}.com', 'title': f'Watch {i}'}
            )
            mock_datastore['watching'][watch['uuid']] = watch
            watches.append(watch)

        # Test 1: Deepcopy shares datastore reference (doesn't copy it)
        watch_copy = deepcopy(watches[0])

        self.assertIsNotNone(watch_copy._datastore,
                            "__datastore should exist in copied watch")
        self.assertIs(watch_copy._datastore, watches[0]._datastore,
                     "__datastore should be SHARED (same object), not copied")
        self.assertIs(watch_copy._datastore, mock_datastore,
                     "__datastore should reference the original datastore")

        # Test 2: Dict data is properly copied (not shared)
        self.assertEqual(watch_copy['title'], 'Watch 0', "Dict data should be copied")
        watch_copy['title'] = 'MODIFIED'
        self.assertNotEqual(watches[0]['title'], 'MODIFIED',
                           "Modifying copy should not affect original")

        # Test 3: Verify no nested datastore copies in watch dict
        # The dict should only contain watch settings, not the datastore
        watch_dict = dict(watch_copy)
        self.assertNotIn('__datastore', watch_dict,
                        "__datastore should not be in dict keys")
        self.assertNotIn('_model__datastore', watch_dict,
                        "_model__datastore should not be in dict keys")

        # Test 4: Multiple deepcopies don't cause exponential memory growth
        # If datastore was copied, each copy would contain 3 watches,
        # and those watches would contain the datastore, etc. (infinite recursion)
        copies = []
        for _ in range(5):
            copies.append(deepcopy(watches[0]))

        # All copies should share the same datastore
        for copy in copies:
            self.assertIs(copy._datastore, mock_datastore,
                         "All copies should share the original datastore")

    def test_watch_pickle_doesnt_serialize_datastore(self):
        """
        Ensure pickle/unpickle doesn't serialize __datastore.

        This is important for multiprocessing and caching - we don't want
        to serialize the entire datastore when pickling a watch.
        """
        mock_datastore = {
            'settings': {'application': {}},
            'watching': {}
        }

        watch = Watch.model(
            __datastore=mock_datastore,
            datastore_path='/tmp/test',
            default={'url': 'https://example.com', 'title': 'Test Watch'}
        )

        # Pickle and unpickle
        pickled = pickle.dumps(watch)
        unpickled_watch = pickle.loads(pickled)

        # Test 1: Watch data is preserved
        self.assertEqual(unpickled_watch['url'], 'https://example.com',
                        "Dict data should be preserved after pickle/unpickle")

        # Test 2: __datastore is NOT serialized (attribute shouldn't exist after unpickle)
        self.assertFalse(hasattr(unpickled_watch, '_datastore'),
                         "__datastore attribute should not exist after unpickle (not serialized)")

        # Test 3: Pickled data shouldn't contain the large datastore object
        # If datastore was serialized, the pickle size would be much larger
        pickle_size = len(pickled)
        # A single watch should be small (< 10KB), not include entire datastore
        self.assertLess(pickle_size, 10000,
                       f"Pickled watch too large ({pickle_size} bytes) - might include datastore")

    def test_tag_deepcopy_works(self):
        """
        Ensure Tag objects (which also inherit from watch_base) can be deepcopied.

        Tags now have optional __datastore for consistency with Watch objects.
        """
        mock_datastore = {
            'settings': {'application': {}},
            'watching': {}
        }

        # Test 1: Tag without datastore (backward compatibility)
        tag_without_ds = Tag.model(
            datastore_path='/tmp/test',
            default={'title': 'Test Tag', 'overrides_watch': True}
        )
        tag_copy1 = deepcopy(tag_without_ds)
        self.assertEqual(tag_copy1['title'], 'Test Tag', "Tag data should be copied")

        # Test 2: Tag with datastore (new pattern for consistency)
        tag_with_ds = Tag.model(
            datastore_path='/tmp/test',
            __datastore=mock_datastore,
            default={'title': 'Test Tag With DS', 'overrides_watch': True}
        )

        # Deepcopy should work
        tag_copy2 = deepcopy(tag_with_ds)

        # Test 3: Dict data is copied
        self.assertEqual(tag_copy2['title'], 'Test Tag With DS', "Tag data should be copied")

        # Test 4: Modifications to copy don't affect original
        tag_copy2['title'] = 'MODIFIED'
        self.assertNotEqual(tag_with_ds['title'], 'MODIFIED',
                           "Modifying copy should not affect original")

        # Test 5: Tag with datastore shares it (doesn't copy it)
        if hasattr(tag_with_ds, '_datastore'):
            self.assertIs(tag_copy2._datastore, tag_with_ds._datastore,
                         "Tag should share __datastore reference like Watch does")

    def test_watch_copy_performance(self):
        """
        Verify that our __deepcopy__ implementation doesn't cause performance issues.

        With the fix, deepcopy should be fast because we're sharing datastore
        instead of copying it.
        """
        import time

        # Create a watch with large datastore (many watches)
        mock_datastore = {
            'settings': {'application': {}},
            'watching': {}
        }

        # Add 100 watches to the datastore
        for i in range(100):
            w = Watch.model(
                __datastore=mock_datastore,
                datastore_path='/tmp/test',
                default={'url': f'https://example{i}.com'}
            )
            mock_datastore['watching'][w['uuid']] = w

        # Time how long deepcopy takes
        watch = list(mock_datastore['watching'].values())[0]

        start = time.time()
        for _ in range(10):
            _ = deepcopy(watch)
        elapsed = time.time() - start

        # Should be fast (< 0.1 seconds for 10 copies)
        # If datastore was copied, it would take much longer
        self.assertLess(elapsed, 0.5,
                       f"Deepcopy too slow ({elapsed:.3f}s for 10 copies) - might be copying datastore")

if __name__ == '__main__':
    unittest.main()
