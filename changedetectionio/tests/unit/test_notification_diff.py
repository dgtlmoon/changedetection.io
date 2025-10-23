#!/usr/bin/env python3

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_notification_diff

import unittest
import os

from changedetectionio import diff

# mostly
class TestDiffBuilder(unittest.TestCase):

    def test_expected_diff_output(self):
        base_dir = os.path.dirname(__file__)
        with open(base_dir + "/test-content/before.txt", 'r') as f:
            previous_version_file_contents = f.read()

        with open(base_dir + "/test-content/after.txt", 'r') as f:
            newest_version_file_contents = f.read()

        output = diff.render_diff(previous_version_file_contents=previous_version_file_contents,
                                  newest_version_file_contents=newest_version_file_contents)

        output = output.split("\n")

        # Check that placeholders are present (they get replaced in apply_service_tweaks)
        self.assertTrue(any(diff.CHANGED_PLACEMARKER_OPEN in line and 'ok' in line for line in output))
        self.assertTrue(any(diff.CHANGED_INTO_PLACEMARKER_OPEN in line and 'xok' in line for line in output))
        self.assertTrue(any(diff.CHANGED_INTO_PLACEMARKER_OPEN in line and 'next-x-ok' in line for line in output))
        self.assertTrue(any(diff.ADDED_PLACEMARKER_OPEN in line and 'and something new' in line for line in output))

        with open(base_dir + "/test-content/after-2.txt", 'r') as f:
            newest_version_file_contents = f.read()
        output = diff.render_diff(previous_version_file_contents, newest_version_file_contents)
        output = output.split("\n")
        self.assertTrue(any(diff.REMOVED_PLACEMARKER_OPEN in line and 'for having learned computerese,' in line for line in output))
        self.assertTrue(any(diff.REMOVED_PLACEMARKER_OPEN in line and 'I continue to examine bits, bytes and words' in line for line in output))

        #diff_removed
        with open(base_dir + "/test-content/before.txt", 'r') as f:
            previous_version_file_contents = f.read()

        with open(base_dir + "/test-content/after.txt", 'r') as f:
            newest_version_file_contents = f.read()
        output = diff.render_diff(previous_version_file_contents, newest_version_file_contents, include_equal=False, include_removed=True, include_added=False)
        output = output.split("\n")
        self.assertTrue(any(diff.CHANGED_PLACEMARKER_OPEN in line and 'ok' in line for line in output))
        self.assertTrue(any(diff.CHANGED_INTO_PLACEMARKER_OPEN in line and 'xok' in line for line in output))
        self.assertTrue(any(diff.CHANGED_INTO_PLACEMARKER_OPEN in line and 'next-x-ok' in line for line in output))
        self.assertFalse(any(diff.ADDED_PLACEMARKER_OPEN in line and 'and something new' in line for line in output))

        #diff_removed
        with open(base_dir + "/test-content/after-2.txt", 'r') as f:
            newest_version_file_contents = f.read()
        output = diff.render_diff(previous_version_file_contents, newest_version_file_contents, include_equal=False, include_removed=True, include_added=False)
        output = output.split("\n")
        self.assertTrue(any(diff.REMOVED_PLACEMARKER_OPEN in line and 'for having learned computerese,' in line for line in output))
        self.assertTrue(any(diff.REMOVED_PLACEMARKER_OPEN in line and 'I continue to examine bits, bytes and words' in line for line in output))

    def test_expected_diff_patch_output(self):
        base_dir = os.path.dirname(__file__)
        with open(base_dir + "/test-content/before.txt", 'r') as f:
            before = f.read()
        with open(base_dir + "/test-content/after.txt", 'r') as f:
            after = f.read()

        output = diff.render_diff(previous_version_file_contents=before,
                                  newest_version_file_contents=after,
                                  patch_format=True)
        output = output.split("\n")

        self.assertIn('-ok', output)
        self.assertIn('+xok', output)
        self.assertIn('+next-x-ok', output)
        self.assertIn('+and something new', output)

        # @todo test blocks of changed, blocks of added, blocks of removed

if __name__ == '__main__':
    unittest.main()
