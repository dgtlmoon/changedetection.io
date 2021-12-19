#!/usr/bin/python3

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_notification_diff

import unittest
import os

from changedetectionio import diff

# mostly
class TestDiffBuilder(unittest.TestCase):

    def test_expected_diff_output(self):
        base_dir=os.path.dirname(__file__)
        output = diff.render_diff(base_dir+"/test-content/before.txt", base_dir+"/test-content/after.txt")
        output = output.split("\n")
        self.assertIn("(changed) ok", output)
        self.assertIn("(-> into) xok", output)
        self.assertIn("(added) and something new", output)

        # @todo test blocks of changed, blocks of added, blocks of removed

if __name__ == '__main__':
    unittest.main()