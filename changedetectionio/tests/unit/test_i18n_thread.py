#!/usr/bin/env python3

"""Tests for the translation helpers used outside of a request context.

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_i18n_thread

flask_babel resolves the locale from the *request*. Background threads, worker
threads and socket.io emits have no request, so gettext() silently returned the
ENGLISH string there - which is why the bulk action toasts (#4481) and the live
watch list columns (#4482) came out in English on a translated page.

See changedetectionio/i18n_thread.py.
"""

import os
import threading
import unittest
from pathlib import Path

from flask import Flask, request, session
from flask_babel import Babel, gettext


def _make_app():
    """A minimal Flask+Babel app pointing at the project's own catalogues.

    The locale selector mirrors the one in changedetectionio/flask_app.py - the
    session (the language the user picked) wins over the browser header.
    """

    def select_locale():
        if 'locale' in session:
            return session['locale']
        return request.accept_languages.best_match(['en_GB', 'ja'])

    app = Flask(__name__)
    app.secret_key = 'test'
    app.config['BABEL_TRANSLATION_DIRECTORIES'] = str(Path(__file__).parent.parent.parent / 'translations')
    app.config['BABEL_DEFAULT_LOCALE'] = 'en_GB'
    Babel(app, locale_selector=select_locale)
    return app


class TestI18nThread(unittest.TestCase):

    def setUp(self):
        self.app = _make_app()

    def test_gettext_is_english_without_a_locale(self):
        """Outside of a request (and without a forced locale) it is English."""
        from changedetectionio.i18n_thread import translation_scope

        with self.app.app_context():
            with translation_scope(app=self.app, locale=None):
                self.assertEqual(gettext('Not yet'), 'Not yet')

    def test_translation_scope_forces_the_locale(self):
        """The whole point - a forced locale translates inside a thread."""
        from changedetectionio.i18n_thread import translation_scope

        with self.app.app_context():
            with translation_scope(app=self.app, locale='ja'):
                self.assertEqual(gettext('Not yet'), '未実施')
                self.assertEqual(gettext('{} watches deleted').format(2),
                                 '{} 件のウォッチを削除しました'.format(2))

    def test_translation_scope_pushes_an_app_context_when_needed(self):
        """No app context at all - it has to make its own."""
        from changedetectionio.i18n_thread import translation_scope

        with translation_scope(app=self.app, locale='ja'):
            self.assertEqual(gettext('Not yet'), '未実施')

    def test_translation_scope_restores_the_previous_locale(self):
        """Forcing a locale must not leak into the code that runs after it."""
        from changedetectionio.i18n_thread import translation_scope

        with self.app.app_context():
            with translation_scope(app=self.app, locale='ja'):
                self.assertEqual(gettext('Not yet'), '未実施')

            # A request afterwards still uses its own language.
            with self.app.test_request_context('/'):
                self.assertEqual(gettext('Not yet'), 'Not yet')

    def test_translation_scope_does_not_swallow_exceptions(self):
        """An error inside the block must still reach the caller."""
        from changedetectionio.i18n_thread import translation_scope

        with self.app.app_context():
            with self.assertRaises(ValueError):
                with translation_scope(app=self.app, locale='ja'):
                    raise ValueError("boom")

    def test_an_unusable_locale_does_not_raise(self):
        """A broken locale must not take the whole thread down."""
        from changedetectionio.i18n_thread import translation_scope

        with self.app.app_context():
            with translation_scope(app=self.app, locale='not-a-locale'):
                self.assertEqual(gettext('Not yet'), 'Not yet')

    def test_capture_locale_inside_a_request(self):
        """The locale is read from the request (session first)."""
        from changedetectionio.i18n_thread import capture_locale

        with self.app.test_request_context('/'):
            session['locale'] = 'ja'
            self.assertEqual(capture_locale(), 'ja')

    def test_capture_locale_without_a_locale_to_read(self):
        """When the locale cannot be read, it must not raise - it returns None."""
        import changedetectionio.i18n_thread as i18n_thread

        def broken():
            raise RuntimeError("Working outside of request context.")

        original = i18n_thread.get_locale
        i18n_thread.get_locale = broken
        try:
            self.assertIsNone(i18n_thread.capture_locale())
        finally:
            i18n_thread.get_locale = original

    def test_translation_works_in_a_thread_without_a_request(self):
        """The real use case - a worker thread that has to build a message."""
        from changedetectionio.i18n_thread import capture_locale, translation_scope

        results = {}

        def worker():
            with translation_scope(app=self.app, locale='ja'):
                results['message'] = gettext('{} watches deleted').format(3)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()

        self.assertEqual(results.get('message'), '3 件のウォッチを削除しました')


if __name__ == '__main__':
    unittest.main()
