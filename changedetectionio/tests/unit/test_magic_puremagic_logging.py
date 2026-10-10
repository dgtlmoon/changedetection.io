#!/usr/bin/env python3
# coding=utf-8

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_magic_puremagic_logging

"""puremagic raises PureError when no file signature matches, which is the normal result for
plain text and most HTML, and ValueError on empty input. Neither is an error and neither should
be logged as a warning, but any other failure from puremagic still should be."""

import unittest
from unittest import mock

from loguru import logger

from changedetectionio.processors.magic import guess_stream_type


class TestPuremagicLogging(unittest.TestCase):

    def setUp(self):
        self.records = []
        self.sink_id = logger.add(lambda m: self.records.append(m.record), level="DEBUG")

    def tearDown(self):
        logger.remove(self.sink_id)

    def warnings(self):
        return [r for r in self.records if r["level"].name == "WARNING" and "puremagic" in r["message"]]

    def test_unidentified_content_is_not_a_warning(self):
        result = guess_stream_type(http_content_header="text/plain", content="just some plain text, no signature")
        self.assertTrue(result.is_plaintext)
        self.assertEqual(self.warnings(), [])

    def test_empty_content_is_not_a_warning(self):
        guess_stream_type(http_content_header="text/html", content="")
        self.assertEqual(self.warnings(), [])

    def test_other_puremagic_failures_still_warn(self):
        with mock.patch("puremagic.magic_string", side_effect=ValueError("boom")):
            result = guess_stream_type(http_content_header="text/plain", content="just some plain text")
        self.assertTrue(result.is_plaintext)
        self.assertEqual(len(self.warnings()), 1)


if __name__ == '__main__':
    unittest.main()
