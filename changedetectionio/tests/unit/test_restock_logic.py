#!/usr/bin/env python3

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_restock_logic

import unittest
import os

from changedetectionio.processors import restock_diff

# mostly
class TestDiffBuilder(unittest.TestCase):

    def test_logic(self):
        assert restock_diff.is_between(number=10, lower=9, upper=11) == True, "Between 9 and 11"
        assert restock_diff.is_between(number=10, lower=0, upper=11) == True, "Between 9 and 11"
        assert restock_diff.is_between(number=10, lower=None, upper=11) == True, "Between None and 11"
        assert not restock_diff.is_between(number=12, lower=None, upper=11) == True, "12 is not between None and 11"

if __name__ == '__main__':
    unittest.main()
