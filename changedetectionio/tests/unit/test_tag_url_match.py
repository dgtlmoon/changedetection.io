#!/usr/bin/env python3

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_tag_url_match

import unittest
from changedetectionio.model.Tag import model as TagModel


def make_tag(pattern):
    """Minimal Tag instance for testing matches_url — skips datastore wiring."""
    tag = TagModel.__new__(TagModel)
    dict.__init__(tag)
    tag['url_match_pattern'] = pattern
    return tag


class TestTagUrlMatch(unittest.TestCase):

    def test_wildcard_matches(self):
        tag = make_tag('*example.com*')
        self.assertTrue(tag.matches_url('https://example.com/page'))
        self.assertTrue(tag.matches_url('https://www.example.com/shop/item'))
        self.assertFalse(tag.matches_url('https://other.com/page'))

    def test_wildcard_case_insensitive(self):
        tag = make_tag('*EXAMPLE.COM*')
        self.assertTrue(tag.matches_url('https://example.com/page'))

    def test_substring_match(self):
        tag = make_tag('github.com/myorg')
        self.assertTrue(tag.matches_url('https://github.com/myorg/repo'))
        self.assertFalse(tag.matches_url('https://github.com/otherorg/repo'))

    def test_substring_case_insensitive(self):
        tag = make_tag('GitHub.com/MyOrg')
        self.assertTrue(tag.matches_url('https://github.com/myorg/repo'))

    def test_empty_pattern_never_matches(self):
        tag = make_tag('')
        self.assertFalse(tag.matches_url('https://example.com'))

    def test_empty_url_never_matches(self):
        tag = make_tag('*example.com*')
        self.assertFalse(tag.matches_url(''))

    def test_question_mark_wildcard(self):
        tag = make_tag('https://example.com/item-?')
        self.assertTrue(tag.matches_url('https://example.com/item-1'))
        self.assertFalse(tag.matches_url('https://example.com/item-12'))

    def test_substring_is_broad(self):
        """Plain substring matching is intentionally broad — 'evil.com' matches anywhere
        in the URL string, including 'notevil.com'. Users who need precise domain matching
        should use a wildcard pattern like '*://evil.com/*' instead."""
        tag = make_tag('evil.com')
        self.assertTrue(tag.matches_url('https://evil.com/page'))
        self.assertTrue(tag.matches_url('https://notevil.com'))  # substring match — expected

    def test_precise_domain_match_with_wildcard(self):
        """Use wildcard pattern for precise domain matching to avoid substring surprises."""
        tag = make_tag('*://evil.com/*')
        self.assertTrue(tag.matches_url('https://evil.com/page'))
        self.assertFalse(tag.matches_url('https://notevil.com/page'))


if __name__ == '__main__':
    unittest.main()
