#!/usr/bin/env python3

"""A group/tag title must map to its own CSS class, whatever alphabet it is written in.

The auto colour for a group is emitted as a stylesheet rule keyed on the class name that
`sanitize_tag_class` derives from the title (see groups-overview.html / watch-overview.html).

The original filter built that class by stripping every non-alphanumeric character, which for
an ASCII title was fine but for a title written entirely in Japanese, Chinese, Korean, Cyrillic
(etc.) stripped the whole string - so every one of those groups fell through to the literal
`tag-tag` class, shared one stylesheet rule, and rendered in the same colour (#4451).

Hashing the title instead keeps the output in [0-9a-f] (always a valid class name) while giving
every distinct title a distinct class.

run from dir above changedetectionio/ dir
python3 -m unittest changedetectionio.tests.unit.test_sanitize_tag_class
"""

import re
import unittest

from changedetectionio.flask_app import _jinja2_filter_sanitize_tag_class as sanitize_tag_class

# The class is used as `tag-{{ class_name }}`, so it may only contain characters that are legal
# in a CSS identifier - and must never be empty.
CSS_SAFE = re.compile(r'^[0-9a-f]+$')


class TestSanitizeTagClass(unittest.TestCase):

    def test_output_is_always_a_safe_css_identifier(self):
        """Whatever goes in, what comes out must be usable as `.tag-<name>`"""
        titles = [
            'Price drops',
            'price drops',
            '価格変動',
            '가격 변동',
            '价格变动',
            'Цена',
            'Ελλάδα',
            '🚨 alerts',
            'a b\tc\nd',
            'has "quotes" and {braces}',
            '../../etc/passwd',
            '} .foo { background-color: red;',
            '-',
            '0',
            ' ',
            '',
        ]
        for title in titles:
            with self.subTest(title=title):
                class_name = sanitize_tag_class(title)
                self.assertTrue(class_name, f"{title!r} must not produce an empty class name")
                self.assertRegex(class_name, CSS_SAFE,
                                 f"{title!r} produced a class name that would break the stylesheet")

    def test_non_ascii_titles_get_their_own_class(self):
        """#4451 - these all collapsed to the same class, so they all got the same auto colour"""
        titles = ['価格変動', '在庫状況', '空室情報']
        class_names = [sanitize_tag_class(t) for t in titles]

        self.assertEqual(len(set(class_names)), len(titles),
                         f"non-ASCII group titles must not share a class name, got {class_names}")
        for class_name in class_names:
            self.assertNotEqual(class_name, 'tag',
                                "non-ASCII titles must not fall back to the shared 'tag' class")

    def test_titles_that_differ_only_in_punctuation_get_their_own_class(self):
        """Stripping non-alphanumerics also merged these; the auto colour must still differ"""
        self.assertNotEqual(sanitize_tag_class('re-stock'), sanitize_tag_class('restock'))
        self.assertNotEqual(sanitize_tag_class('My Tag'), sanitize_tag_class('my tag'))

    def test_is_stable(self):
        """The rule and the element that uses it are rendered by separate calls - they must agree"""
        for title in ['Price drops', '価格変動', '']:
            with self.subTest(title=title):
                self.assertEqual(sanitize_tag_class(title), sanitize_tag_class(title))

    def test_is_deterministic_across_runs(self):
        """Not salted/randomised per process, so a class name can be relied on in a test or CSS"""
        self.assertEqual(sanitize_tag_class('Price drops'), '03d0b363b6f919cc')
        self.assertEqual(sanitize_tag_class('価格変動'), 'd42fc3593d9c3c5a')

    def test_many_titles_stay_unique(self):
        titles = [f"group {i}" for i in range(500)] + [f"グループ{i}" for i in range(500)]
        class_names = {sanitize_tag_class(t) for t in titles}
        self.assertEqual(len(class_names), len(titles), "class names must not collide")


if __name__ == '__main__':
    unittest.main()
