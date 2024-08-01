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


        self.assertIn('(changed) ok', output)
        self.assertIn('(into) xok', output)
        self.assertIn('(into) next-x-ok', output)
        self.assertIn('(added) and something new', output)

        with open(base_dir + "/test-content/after-2.txt", 'r') as f:
            newest_version_file_contents = f.read()
        output = diff.render_diff(previous_version_file_contents, newest_version_file_contents)
        output = output.split("\n")
        self.assertIn('(removed) for having learned computerese,', output)
        self.assertIn('(removed) I continue to examine bits, bytes and words', output)

        #diff_removed
        with open(base_dir + "/test-content/before.txt", 'r') as f:
            previous_version_file_contents = f.read()

        with open(base_dir + "/test-content/after.txt", 'r') as f:
            newest_version_file_contents = f.read()
        output = diff.render_diff(previous_version_file_contents, newest_version_file_contents, include_equal=False, include_removed=True, include_added=False)
        output = output.split("\n")
        self.assertIn('(changed) ok', output)
        self.assertIn('(into) xok', output)
        self.assertIn('(into) next-x-ok', output)
        self.assertNotIn('(added) and something new', output)

        #diff_removed
        with open(base_dir + "/test-content/after-2.txt", 'r') as f:
            newest_version_file_contents = f.read()
        output = diff.render_diff(previous_version_file_contents, newest_version_file_contents, include_equal=False, include_removed=True, include_added=False)
        output = output.split("\n")
        self.assertIn('(removed) for having learned computerese,', output)
        self.assertIn('(removed) I continue to examine bits, bytes and words', output)

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
