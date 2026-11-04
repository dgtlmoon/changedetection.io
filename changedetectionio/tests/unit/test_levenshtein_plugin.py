from changedetectionio.conditions.plugins.levenshtein_plugin import levenshtein_ratio_recent_history
from changedetectionio.store import ChangeDetectionStore
import shutil
import tempfile
import time
import unittest
import uuid


class TestLevenshteinRatioRecentHistory(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for the test datastore
        self.test_datastore_path = tempfile.mkdtemp()

        # Initialize ChangeDetectionStore with our test path and no default watches
        self.store = ChangeDetectionStore(
            datastore_path=self.test_datastore_path,
            include_default_watches=False
        )

        # Add a test watch
        watch_url = "https://example.com"
        self.watch_uuid = self.store.add_watch(url=watch_url)
        self.watch = self.store.data['watching'][self.watch_uuid]

        # Two prior snapshots, deliberately very similar to each other so that a
        # correct comparison yields a high ratio, and an incorrect one (comparing
        # against a raw timestamp string) yields a near-zero ratio.
        self.first_content = "The quick brown fox jumps over the lazy dog near the riverbank at dawn."
        self.second_content = "The quick brown fox jumps over the lazy dog near the riverbank at dusk."

        timestamp1 = int(time.time())
        self.watch.save_history_blob(contents=self.first_content,
                                      timestamp=timestamp1,
                                      snapshot_id=str(uuid.uuid4()))

        timestamp2 = timestamp1 + 60
        self.watch.save_history_blob(contents=self.second_content,
                                      timestamp=timestamp2,
                                      snapshot_id=str(uuid.uuid4()))

        self.assertEqual(len(self.watch.history), 2)

    def tearDown(self):
        self.store.stop_thread = True
        time.sleep(0.5)
        shutil.rmtree(self.test_datastore_path)

    def test_empty_incoming_text_compares_against_previous_snapshot(self):
        """
        Regression test: when incoming_text == "" (e.g. a filter matched nothing
        this cycle), the function must fall back to comparing the latest saved
        snapshot against the *previous saved snapshot's text*, not against a raw
        history timestamp key/string.
        """
        result = levenshtein_ratio_recent_history(self.watch, incoming_text="")

        self.assertIsInstance(result, dict)

        # The two snapshots differ by one word ("dawn" vs "dusk"), so a correct
        # comparison should show high similarity.
        self.assertGreater(result['percent_similar'], 90)

        # Sanity check against directly comparing the two known snapshot contents.
        from Levenshtein import ratio
        expected_ratio = ratio(self.second_content, self.first_content)
        self.assertAlmostEqual(result['ratio'], expected_ratio, places=6)

    def test_incoming_text_none_still_compares_last_two_snapshots(self):
        # Existing behaviour (used by ui_edit_stats_extras) should be unaffected
        result = levenshtein_ratio_recent_history(self.watch)
        self.assertIsInstance(result, dict)
        self.assertGreater(result['percent_similar'], 90)

    def test_incoming_text_provided_is_used_directly(self):
        # When there IS incoming text, it should be compared directly against
        # the latest saved snapshot, not the history.
        incoming = "Something completely different that shares almost nothing."
        result = levenshtein_ratio_recent_history(self.watch, incoming_text=incoming)
        self.assertIsInstance(result, dict)

        from Levenshtein import ratio
        expected_ratio = ratio(self.second_content, incoming)
        self.assertAlmostEqual(result['ratio'], expected_ratio, places=6)

    def test_single_snapshot_with_empty_incoming_text_does_not_crash(self):
        # With only one snapshot in history, there's nothing to fall back to -
        # this should not raise, and should not produce a bogus comparison.
        single_snapshot_store_path = tempfile.mkdtemp()
        try:
            store = ChangeDetectionStore(
                datastore_path=single_snapshot_store_path,
                include_default_watches=False
            )
            watch_uuid = store.add_watch(url="https://example.org")
            watch = store.data['watching'][watch_uuid]
            watch.save_history_blob(contents="Only one snapshot here",
                                     timestamp=int(time.time()),
                                     snapshot_id=str(uuid.uuid4()))
            self.assertEqual(len(watch.history), 1)

            result = levenshtein_ratio_recent_history(watch, incoming_text="")
            # No second snapshot to compare against, so we expect no result
            # rather than a misleading ratio against a timestamp string.
            self.assertEqual(result, '')

            store.stop_thread = True
            time.sleep(0.5)
        finally:
            shutil.rmtree(single_snapshot_store_path)


if __name__ == '__main__':
    unittest.main()
