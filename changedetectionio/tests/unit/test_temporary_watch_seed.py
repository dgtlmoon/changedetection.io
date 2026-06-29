#!/usr/bin/env python3
"""
Unit tests for promoting an Add-Watch live snapshot into a real watch.

The Add Watch UI fetches a screenshot + xpath element data once (the "/snapshot"
endpoint), parks it under datastore/temporary/{uuid} in final on-disk format, and
on submit renames that directory into place as the new watch's data_dir - so the
watch is created without fetching the page a second time.

Run from the tests/ directory:
    python -m unittest unit/test_temporary_watch_seed.py
"""

import json
import os
import shutil
import tempfile
import time
import unittest
import uuid
import zlib

from changedetectionio.store import ChangeDetectionStore


class TestTemporaryWatchSeed(unittest.TestCase):
    def setUp(self):
        self.test_datastore_path = tempfile.mkdtemp()
        self.store = ChangeDetectionStore(
            datastore_path=self.test_datastore_path,
            include_default_watches=False,
        )

    def tearDown(self):
        self.store.stop_thread = True
        time.sleep(0.5)
        shutil.rmtree(self.test_datastore_path, ignore_errors=True)

    def _make_temp_snapshot(self, temp_uuid=None):
        """Create a temporary/{uuid} dir in final watch on-disk format, as /snapshot does."""
        temp_uuid = temp_uuid or str(uuid.uuid4())
        temp_dir = self.store.get_temporary_watch_dir(temp_uuid)
        os.makedirs(temp_dir, exist_ok=True)
        with open(os.path.join(temp_dir, "last-screenshot.png"), 'wb') as f:
            f.write(b"FAKE-SCREENSHOT-BYTES")
        with open(os.path.join(temp_dir, "elements.deflate"), 'wb') as f:
            f.write(zlib.compress(json.dumps([{"xpath": "//h1", "width": 10}]).encode()))
        return temp_uuid, temp_dir

    def test_promote_renames_snapshot_into_watch(self):
        temp_uuid, temp_dir = self._make_temp_snapshot()

        new_uuid = self.store.make_temporary_watch_active_watch(
            temp_uuid=temp_uuid,
            url="https://example.com",
            extras={'paused': True},
        )

        self.assertIsNotNone(new_uuid)
        watch = self.store.data['watching'][new_uuid]

        # The two seed files are now in the watch's data_dir...
        self.assertTrue(os.path.isfile(os.path.join(watch.data_dir, "last-screenshot.png")))
        self.assertTrue(os.path.isfile(os.path.join(watch.data_dir, "elements.deflate")))
        # ...the visual selector reports ready (no re-fetch needed)...
        self.assertTrue(self.store.visualselector_data_is_ready(new_uuid))
        # ...the watch.json was committed alongside the seeded files...
        self.assertTrue(os.path.isfile(os.path.join(watch.data_dir, "watch.json")))
        # ...and it was a move, not a copy: the temp dir is gone.
        self.assertFalse(os.path.exists(temp_dir))

        # Screenshot content survived the rename intact.
        with open(os.path.join(watch.data_dir, "last-screenshot.png"), 'rb') as f:
            self.assertEqual(f.read(), b"FAKE-SCREENSHOT-BYTES")

    def test_falls_back_to_normal_add_when_uuid_missing(self):
        # No snapshot was ever parked - submit must still create a working watch.
        new_uuid = self.store.make_temporary_watch_active_watch(
            temp_uuid='',
            url="https://example.com",
        )
        self.assertIsNotNone(new_uuid)
        self.assertIn(new_uuid, self.store.data['watching'])
        self.assertFalse(self.store.visualselector_data_is_ready(new_uuid))

    def test_falls_back_when_temp_dir_does_not_exist(self):
        # A well-formed but unknown uuid (e.g. expired/cleaned) must not error.
        new_uuid = self.store.make_temporary_watch_active_watch(
            temp_uuid=str(uuid.uuid4()),
            url="https://example.com",
        )
        self.assertIsNotNone(new_uuid)
        self.assertIn(new_uuid, self.store.data['watching'])

    def test_path_traversal_uuid_is_rejected(self):
        # The temp_uuid arrives from a client POST field - must not escape temporary/.
        self.assertIsNone(self.store.get_temporary_watch_dir("../../etc"))
        self.assertIsNone(self.store.get_temporary_watch_dir("not-a-uuid"))
        self.assertIsNone(self.store.get_temporary_watch_dir(""))
        self.assertIsNone(self.store.get_temporary_watch_dir(None))
        # A valid v4 uuid resolves to a path directly under temporary/
        good = str(uuid.uuid4())
        resolved = self.store.get_temporary_watch_dir(good)
        self.assertIsNotNone(resolved)
        self.assertEqual(os.path.basename(resolved), good)

    def test_processor_consumes_preloaded_fetch_without_network(self):
        # Create a watch and drop a preload bundle into its data_dir, as the Add Watch
        # snapshot -> migrate flow would. The processor's call_browser() seam should then
        # populate its fetcher from disk instead of hitting the network.
        from changedetectionio.processors.text_json_diff.processor import perform_site_check

        new_uuid = self.store.add_watch(url="https://example.com", extras={'paused': True})
        watch = self.store.data['watching'][new_uuid]
        watch.ensure_data_dir_exists()

        html = "<html><body><h1>Hello preloaded world</h1></body></html>"
        with open(os.path.join(watch.data_dir, "last-screenshot.png"), 'wb') as f:
            f.write(b"FAKE-SCREENSHOT-BYTES")
        with open(os.path.join(watch.data_dir, "elements.deflate"), 'wb') as f:
            f.write(zlib.compress(json.dumps([{"xpath": "//h1"}]).encode()))
        preload_path = os.path.join(watch.data_dir, "preload-fetch.json")
        with open(preload_path, 'w', encoding='utf-8') as f:
            json.dump({"content": html, "status_code": 200,
                       "headers": {"content-type": "text/html"}}, f)

        handler = perform_site_check(datastore=self.store, watch_uuid=new_uuid)
        consumed = handler._consume_preloaded_fetch()

        self.assertTrue(consumed)
        # Fetcher is populated as if a real fetch happened...
        self.assertEqual(handler.fetcher.content, html)
        self.assertEqual(handler.fetcher.get_last_status_code(), 200)
        self.assertEqual(handler.fetcher.get_all_headers().get('content-type'), 'text/html')
        self.assertEqual(handler.fetcher.screenshot, b"FAKE-SCREENSHOT-BYTES")
        self.assertEqual(handler.fetcher.xpath_data, [{"xpath": "//h1"}])
        # ...and the marker is gone, so the next check fetches live (one-shot).
        self.assertFalse(os.path.exists(preload_path))
        self.assertFalse(handler._consume_preloaded_fetch())

    def test_processor_runs_changedetection_on_preloaded_content(self):
        # End-to-end of the worker's two key steps without network: consume preload,
        # then run the processor -> it should produce extracted text + a checksum.
        from changedetectionio.processors.text_json_diff.processor import perform_site_check

        new_uuid = self.store.add_watch(url="https://example.com", extras={'paused': True})
        watch = self.store.data['watching'][new_uuid]
        watch.ensure_data_dir_exists()
        with open(os.path.join(watch.data_dir, "preload-fetch.json"), 'w', encoding='utf-8') as f:
            json.dump({"content": "<html><body><h1>Detect me</h1></body></html>",
                       "status_code": 200, "headers": {"content-type": "text/html"}}, f)

        handler = perform_site_check(datastore=self.store, watch_uuid=new_uuid)
        self.assertTrue(handler._consume_preloaded_fetch())

        changed_detected, update_obj, contents = handler.run_changedetection(watch=handler.watch)

        # First run is always a change; extracted text must contain the page text.
        self.assertTrue(changed_detected)
        self.assertIn("Detect me", contents)
        self.assertTrue(update_obj.get('previous_md5'))

    def test_run_preloaded_first_check_creates_history(self):
        # The blueprint helper should turn a parked snapshot into a real first history
        # snapshot (history.txt + {timestamp}.txt.br) with no network.
        from changedetectionio.blueprint.ui.views import run_preloaded_first_check

        new_uuid = self.store.add_watch(url="https://example.com", extras={'paused': True})
        watch = self.store.data['watching'][new_uuid]
        watch.ensure_data_dir_exists()
        with open(os.path.join(watch.data_dir, "preload-fetch.json"), 'w', encoding='utf-8') as f:
            json.dump({"content": "<html><head><title>T</title></head><body><h1>Detect me</h1></body></html>",
                       "status_code": 200, "headers": {"content-type": "text/html"}}, f)

        created = run_preloaded_first_check(self.store, new_uuid)

        self.assertTrue(created)
        self.assertEqual(watch.history_n, 1)
        # last_checked is stamped to "now" since we effectively just checked it.
        self.assertTrue(watch.get('last_checked'))
        # The extracted text snapshot is retrievable and holds the page text.
        latest_ts = list(watch.history.keys())[-1]
        self.assertIn("Detect me", watch.get_history_snapshot(timestamp=latest_ts))
        # One-shot: the preload marker is consumed.
        self.assertFalse(os.path.exists(os.path.join(watch.data_dir, "preload-fetch.json")))

    def test_run_preloaded_first_check_no_preload_returns_false(self):
        from changedetectionio.blueprint.ui.views import run_preloaded_first_check
        new_uuid = self.store.add_watch(url="https://example.com")
        self.assertFalse(run_preloaded_first_check(self.store, new_uuid))
        self.assertEqual(self.store.data['watching'][new_uuid].history_n, 0)

    def test_cleanup_removes_only_stale_snapshots(self):
        stale_uuid, stale_dir = self._make_temp_snapshot()
        fresh_uuid, fresh_dir = self._make_temp_snapshot()

        # Age the stale one well past the TTL.
        old = time.time() - 7200
        os.utime(stale_dir, (old, old))

        self.store.cleanup_temporary_watches(ttl_seconds=3600)

        self.assertFalse(os.path.exists(stale_dir))
        self.assertTrue(os.path.exists(fresh_dir))


if __name__ == '__main__':
    unittest.main()
