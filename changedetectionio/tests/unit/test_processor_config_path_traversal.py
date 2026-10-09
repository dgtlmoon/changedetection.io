#!/usr/bin/env python3

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_processor_config_path_traversal

"""Regression tests for GHSA-mh42-m7cg-49fr - arbitrary file write via the watch `processor` field.

A watch's `processor` is enum-validated by the API, but /imports/import puts
request.values.get('processor') into the watch verbatim. save_processor_config() then uses that
value as a filename (f'{processor}.json') and update_extra_watch_config() did
os.path.join(data_dir, filename) + open(filepath, 'w') with no containment - so a value like
'../../../../tmp/pwned' escaped the watch directory and wrote an attacker-named JSON file
anywhere the app user could reach. get_extra_watch_config() had the same traversal on read.

Three layers are asserted here: path containment in base.py (the security boundary), the filename
sanity check in save_processor_config(), and add_watch() refusing to persist an unknown processor
at all - which also covers the share-link import path, where 'processor' arrives in JSON fetched
from a remote URL.
"""

import os
import tempfile
import unittest

from changedetectionio.processors.base import difference_detection_processor


class TestWatchConfigPathContainment(unittest.TestCase):
    """The containment helper is the security boundary - every caller goes through it."""

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.base, 'datastore', 'some-watch-uuid')
        os.makedirs(self.data_dir)

    def _resolve(self, filename):
        return difference_detection_processor._resolve_watch_config_path(self.data_dir, filename)

    def test_normal_processor_filenames_are_allowed(self):
        for filename in ('text_json_diff.json', 'restock_diff.json', 'visual_ssim_score.json'):
            with self.subTest(filename=filename):
                got = self._resolve(filename)
                self.assertEqual(got, os.path.join(os.path.realpath(self.data_dir), filename))

    def test_traversal_is_refused(self):
        # The exact shape from the advisory PoC, plus the usual variants
        attempts = (
            '../../../../../../tmp/pwned.json',
            '../pwned.json',
            '..',
            '.',
            '',
            None,
            '/etc/cron.d/pwned.json',
            'subdir/pwned.json',
            '..\\..\\pwned.json',
        )
        for filename in attempts:
            with self.subTest(filename=filename):
                self.assertIsNone(self._resolve(filename),
                                  f"{filename!r} must not resolve to a writable path")

    def test_symlink_inside_the_watch_dir_cannot_redirect_the_write(self):
        """A bare filename is not enough - it must still land inside the directory."""
        outside = os.path.join(self.base, 'outside.json')
        link = os.path.join(self.data_dir, 'evil.json')
        os.symlink(outside, link)
        self.assertIsNone(self._resolve('evil.json'))


class TestSaveProcessorConfigRejectsUnsafeNames(unittest.TestCase):
    """Second layer: the processor name is sanitised before it becomes a filename."""

    def setUp(self):
        from changedetectionio.store import ChangeDetectionStore
        self.datastore_path = tempfile.mkdtemp()
        self.store = ChangeDetectionStore(datastore_path=self.datastore_path,
                                          include_default_watches=False)

    def tearDown(self):
        self.store.stop_thread = True

    def test_traversing_processor_name_writes_nothing(self):
        from changedetectionio.processors import save_processor_config

        uuid = self.store.add_watch(url='https://example.com/x')

        # What /imports/import allows through today (no enum check on that path)
        evil_target = os.path.join(tempfile.mkdtemp(), 'pwned')
        self.store.data['watching'][uuid]['processor'] = f'../../../..{evil_target}'

        ok = save_processor_config(self.store, uuid, {'marker': 'owned'})

        # Assert the file write FIRST - that is the vulnerability itself, and on unfixed code
        # this is the assertion that fires (naming the escaped path in the failure message).
        self.assertFalse(os.path.exists(f'{evil_target}.json'),
                         f"GHSA-mh42-m7cg-49fr: wrote outside the datastore to {evil_target}.json")
        self.assertFalse(ok, "save_processor_config must refuse an unsafe processor name")

    def test_legitimate_processor_name_still_saves(self):
        from changedetectionio.processors import save_processor_config

        uuid = self.store.add_watch(url='https://example.com/x')
        self.store.data['watching'][uuid]['processor'] = 'text_json_diff'

        self.assertTrue(save_processor_config(self.store, uuid, {'marker': 'fine'}))

        written = os.path.join(self.store.data['watching'][uuid].data_dir, 'text_json_diff.json')
        self.assertTrue(os.path.isfile(written), "the legitimate config write must still happen")




class TestAddWatchRejectsUnknownProcessor(unittest.TestCase):
    """Third layer: an unknown processor never gets persisted in the first place.

    add_watch() is the chokepoint for the two callers that don't enum-validate: /imports/import
    (request.values verbatim) and the share-link path, which takes 'processor' out of JSON
    fetched from a remote URL.
    """

    def setUp(self):
        from changedetectionio.store import ChangeDetectionStore
        self.datastore_path = tempfile.mkdtemp()
        self.store = ChangeDetectionStore(datastore_path=self.datastore_path,
                                          include_default_watches=False)

    def tearDown(self):
        self.store.stop_thread = True

    def test_traversing_processor_is_not_stored(self):
        uuid = self.store.add_watch(url='https://example.com/x',
                                    extras={'processor': '../../../../tmp/pwned'})
        self.assertNotEqual(self.store.data['watching'][uuid].get('processor'),
                            '../../../../tmp/pwned',
                            "a path-traversing processor must not be persisted")

    def test_known_processor_is_kept(self):
        uuid = self.store.add_watch(url='https://example.com/x',
                                    extras={'processor': 'restock_diff'})
        self.assertEqual(self.store.data['watching'][uuid].get('processor'), 'restock_diff')


if __name__ == '__main__':
    unittest.main()
