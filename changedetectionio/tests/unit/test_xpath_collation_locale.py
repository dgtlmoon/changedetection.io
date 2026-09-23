#!/usr/bin/env python3

"""An xPath filter must mean the same thing whatever LC_COLLATE the process is in.

elementpath implements the XPath string functions on top of locale.strxfrm:

    def contains(self, a, b):  return self.strxfrm(b) in self.strxfrm(a)

Under LC_COLLATE=C, strxfrm() is the identity and that is an ordinary substring test. Under a
real locale it returns a binary collation key, and a substring of a collation key is not the
collation key of the substring - so contains(), starts-with(), ends-with() and
substring-before/after() return false for EVERY input.

That shipped the day the Docker image started generating its locales: `ENV LC_ALL=en_US.UTF-8`
became satisfiable, flask_app's setlocale() stopped failing, LC_COLLATE went with it, and every
watch whose filter used contains() reported "no filters were found" against a page whose HTML
plainly contained the target (#4437). Nothing in the codebase changed - which is why it survived
a bisect back to 0.60.2 and could only be found by diffing the containers.

Both halves of the fix are asserted here: the filter pins the codepoint collation itself, and
flask_app leaves LC_COLLATE alone.
"""

import locale
import unittest

from changedetectionio import html_tools

HTML = """<html><body>
  <div id="price_box"><p>Only $9.99 per month</p></div>
  <div id="other">nothing to see</div>
</body></html>"""

# Locales that are actually present vary by image; skip rather than fail on a bare CI box.
CANDIDATE_LOCALES = ['en_US.UTF-8', 'C.UTF-8', 'en_GB.UTF-8', 'de_DE.UTF-8']


def _first_available_collate_locale():
    original = locale.setlocale(locale.LC_COLLATE)
    try:
        for loc in CANDIDATE_LOCALES:
            try:
                locale.setlocale(locale.LC_COLLATE, loc)
                return loc
            except locale.Error:
                continue
        return None
    finally:
        locale.setlocale(locale.LC_COLLATE, original)


class TestXpathCollationIsLocaleIndependent(unittest.TestCase):

    def setUp(self):
        self.original_collate = locale.setlocale(locale.LC_COLLATE)

    def tearDown(self):
        locale.setlocale(locale.LC_COLLATE, self.original_collate)

    def test_string_functions_survive_a_utf8_collation(self):
        loc = _first_available_collate_locale()
        if loc is None:
            self.skipTest("no UTF-8 locale generated in this environment")

        # Every one of these is strxfrm-based inside elementpath, and every one of them appears
        # in filters reported against #4437.
        rules = [
            '//*[self::div or self::p][contains(.,"month")]',
            '//div[contains(@id, "_")]',
            '//p[starts-with(., "Only")]',
            '//p[ends-with(., "month")]',
        ]

        locale.setlocale(locale.LC_COLLATE, 'C')
        baseline = {r: html_tools.xpath_filter(xpath_filter=r, html_content=HTML).strip() for r in rules}
        for rule, out in baseline.items():
            self.assertTrue(out, f"{rule} matched nothing even under LC_COLLATE=C")

        locale.setlocale(locale.LC_COLLATE, loc)
        for rule in rules:
            out = html_tools.xpath_filter(xpath_filter=rule, html_content=HTML).strip()
            self.assertEqual(
                out, baseline[rule],
                f"xPath filter {rule!r} behaves differently under LC_COLLATE={loc} than under C - "
                f"the collation is leaking into the filter (#4437)"
            )

    def test_flask_app_does_not_touch_lc_collate(self):
        """The presentation locale must not drag LC_COLLATE along with it.

        flask_app sets LC_CTYPE/LC_NUMERIC/LC_MONETARY/LC_TIME individually rather than LC_ALL.
        A future edit back to locale.LC_ALL would silently reintroduce the bug, so pin it here -
        the source is the honest thing to assert, because the import has long since run.
        """
        from pathlib import Path
        src = Path(html_tools.__file__).parent.joinpath('flask_app.py').read_text()
        self.assertNotIn(
            'locale.setlocale(locale.LC_ALL', src,
            "flask_app must not setlocale(LC_ALL, ...) - it takes LC_COLLATE with it and breaks "
            "every xPath contains() filter (#4437)"
        )


if __name__ == '__main__':
    unittest.main()
