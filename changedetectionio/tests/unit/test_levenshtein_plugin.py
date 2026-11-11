#!/usr/bin/env python3

"""Tests for the Levenshtein condition plugin.

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_levenshtein_plugin

The plugin compares the newest snapshot against the previous one. The fallback used when there is
no incoming text (an empty filtered result is a normal outcome, not an error) originally grabbed
the raw history dict KEY - a timestamp string - instead of the previous snapshot's text, so the
condition silently decided on a meaningless score instead of a real similarity.

See #4287.
"""

import unittest


class FakeWatch:
    """Minimal stand-in for a Watch - only what the plugin actually touches."""

    def __init__(self, history):
        # history: {timestamp: text}
        self.history = history

    def get_history_snapshot(self, timestamp=None, filepath=None):
        return self.history[timestamp]


class TestLevenshteinRecentHistory(unittest.TestCase):

    def _ratio(self, watch, incoming_text):
        from changedetectionio.conditions.plugins.levenshtein_plugin import levenshtein_ratio_recent_history

        result = levenshtein_ratio_recent_history(watch, incoming_text)
        self.assertIsInstance(result, dict, "expected a metrics dict")
        return result

    def test_empty_incoming_text_compares_against_previous_snapshot(self):
        """The regression: empty incoming text must compare snapshot-to-snapshot."""
        history = {
            "1000000000": "The quick brown fox jumps over the lazy dog near the riverbank at dawn.",
            "1000000100": "The quick brown fox jumps over the lazy dog near the riverbank at dusk.",
        }
        watch = FakeWatch(history)

        result = self._ratio(watch, "")

        # Two snapshots that differ only in the last word are ~95% similar.
        # Comparing against the raw timestamp key instead would give 0.0.
        self.assertGreater(result['percent_similar'], 90.0,
                           "empty incoming text must still compare against the previous SNAPSHOT, not its timestamp key")
        self.assertLess(result['percent_similar'], 100.0)

    def test_non_empty_incoming_text_still_wins(self):
        """The normal path must keep comparing against the incoming text.

        'a' is the latest saved snapshot and 'b' is the incoming text, so the incoming
        text here is the NEW version of nearly the same content.
        """
        history = {
            "1000000000": "An older revision of the page content entirely.",
            "1000000100": "The quick brown fox jumps over the lazy dog near the riverbank at dawn.",
        }
        watch = FakeWatch(history)

        result = self._ratio(watch, "The quick brown fox jumps over the lazy dog near the riverbank at dusk.")

        self.assertGreater(result['percent_similar'], 90.0)

    def test_single_snapshot_with_empty_text_returns_no_result(self):
        """With one snapshot and no incoming text there is nothing to compare - don't blow up."""
        watch = FakeWatch({"1000000000": "only one snapshot"})

        from changedetectionio.conditions.plugins.levenshtein_plugin import levenshtein_ratio_recent_history

        result = levenshtein_ratio_recent_history(watch, "")
        self.assertEqual(result, '')

    def test_no_request_context_needed(self):
        """The plugin must not need a Flask request/app context to work."""
        history = {
            "1000000000": "alpha",
            "1000000100": "alpha beta",
        }
        watch = FakeWatch(history)

        # No app context pushed here on purpose - the plugin must work standalone.
        result = self._ratio(watch, "")
        self.assertIn('percent_similar', result)


if __name__ == '__main__':
    unittest.main()
