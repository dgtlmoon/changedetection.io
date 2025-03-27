from changedetectionio.conditions import execute_ruleset_against_all_plugins
from changedetectionio.store import ChangeDetectionStore
import shutil
import tempfile
import time
import unittest
import uuid


class TestTriggerConditions(unittest.TestCase):
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

    def tearDown(self):
      # Clean up the test datastore
      self.store.stop_thread = True
      time.sleep(0.5)  # Give thread time to stop
      shutil.rmtree(self.test_datastore_path)

    def test_conditions_execution_pass(self):
        # Get the watch object
        watch = self.store.data['watching'][self.watch_uuid]

        # Create and save a snapshot
        first_content = "I saw 100 people at a rock show"
        timestamp1 = int(time.time())
        snapshot_id1 = str(uuid.uuid4())
        watch.save_history_text(contents=first_content,
                                timestamp=timestamp1,
                                snapshot_id=snapshot_id1)

        # Add another snapshot
        second_content = "I saw 200 people at a rock show"
        timestamp2 = int(time.time()) + 60
        snapshot_id2 = str(uuid.uuid4())
        watch.save_history_text(contents=second_content,
                                timestamp=timestamp2,
                                snapshot_id=snapshot_id2)

        # Verify both snapshots are stored
        history = watch.history
        self.assertEqual(len(history), 2)

        # Retrieve and check snapshots
        #snapshot1 = watch.get_history_snapshot(str(timestamp1))
        #snapshot2 = watch.get_history_snapshot(str(timestamp2))

        self.store.data['watching'][self.watch_uuid].update(
            {
                "conditions_match_logic": "ALL",
                "conditions": [
                    {"operator": ">=", "field": "extracted_number", "value": "10"},
                    {"operator": "<=", "field": "extracted_number", "value": "5000"},
                    {"operator": "in", "field": "page_text", "value": "rock"},
                    #{"operator": "starts_with", "field": "page_text", "value": "I saw"},
                ]
            }
        )

        # ephemeral_data - some data that could exist before the watch saved a new version
        result = execute_ruleset_against_all_plugins(current_watch_uuid=self.watch_uuid,
                                                     application_datastruct=self.store.data,
                                                     ephemeral_data={'text': "I saw 500 people at a rock show"})

        # @todo - now we can test that 'Extract number' increased more than X since last time
        self.assertTrue(result.get('result'))


if __name__ == '__main__':
    unittest.main()
