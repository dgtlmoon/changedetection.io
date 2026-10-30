#!/usr/bin/env python3

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_werkzeug_logger_level

"""LOGGER_LEVEL / -l must also control werkzeug's HTTP access logger.

loguru and the stdlib logging package are independent. Werkzeug's dev server
emits access lines through logging.getLogger('werkzeug') at INFO, so setting
LOGGER_LEVEL=ERROR currently still prints every GET (issue #4263).
"""

import logging
import unittest

from changedetectionio.stdlib_log_level import (
    apply_stdlib_logger_level,
    stdlib_level_from_logger_level,
)


class TestStdlibLevelFromLoggerLevel(unittest.TestCase):
    def test_named_levels(self):
        self.assertEqual(stdlib_level_from_logger_level('ERROR'), logging.ERROR)
        self.assertEqual(stdlib_level_from_logger_level('error'), logging.ERROR)
        self.assertEqual(stdlib_level_from_logger_level('WARNING'), logging.WARNING)
        self.assertEqual(stdlib_level_from_logger_level('WARN'), logging.WARNING)
        self.assertEqual(stdlib_level_from_logger_level('INFO'), logging.INFO)
        self.assertEqual(stdlib_level_from_logger_level('DEBUG'), logging.DEBUG)
        self.assertEqual(stdlib_level_from_logger_level('CRITICAL'), logging.CRITICAL)

    def test_success_is_quieter_than_info(self):
        # loguru SUCCESS is 25. Access lines are INFO (20), so SUCCESS must hide them.
        self.assertGreater(stdlib_level_from_logger_level('SUCCESS'), logging.INFO)

    def test_trace_still_allows_info_access_lines(self):
        self.assertLessEqual(stdlib_level_from_logger_level('TRACE'), logging.INFO)

    def test_numeric_levels_pass_through(self):
        self.assertEqual(stdlib_level_from_logger_level(40), 40)
        self.assertEqual(stdlib_level_from_logger_level(25), 25)


class TestApplyStdlibLoggerLevel(unittest.TestCase):
    def setUp(self):
        self.werkzeug_log = logging.getLogger('werkzeug')
        self._previous_level = self.werkzeug_log.level
        # Werkzeug sets INFO on first use when the logger is still NOTSET.
        self.werkzeug_log.setLevel(logging.INFO)

    def tearDown(self):
        self.werkzeug_log.setLevel(self._previous_level)

    def test_error_suppresses_werkzeug_info_access_lines(self):
        apply_stdlib_logger_level('ERROR')
        self.assertFalse(self.werkzeug_log.isEnabledFor(logging.INFO))
        self.assertTrue(self.werkzeug_log.isEnabledFor(logging.ERROR))

    def test_info_keeps_werkzeug_access_lines(self):
        apply_stdlib_logger_level('INFO')
        self.assertTrue(self.werkzeug_log.isEnabledFor(logging.INFO))


if __name__ == '__main__':
    unittest.main()
