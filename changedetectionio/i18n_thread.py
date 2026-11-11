"""
Translation helpers for code that runs OUTSIDE a request context.

flask_babel's gettext() resolves the locale from the request. When there is no
request - a background thread, a socket.io emit, a worker - it falls back to the
default locale and silently returns the ENGLISH string, even when a translation
for it exists in the catalogue.

That is what made the bulk action toasts (#4481) and the watch list
"last checked / last changed" columns (#4482) come out in English on a page that
was rendered in another language: the first render happened inside a request, the
update happened in a thread without one.

The display language is per-browser (session['locale'], or the browser's
Accept-Language header - see the get_locale() selector in flask_app.py), so the
watch list rows have to be rendered once per connected client rather than once
for the whole server - see realtime/socket_server.py.

Capture the locale while a request is still around, then re-apply it around the
code that has to translate.
"""
from contextlib import contextmanager

from babel import Locale
from flask import has_app_context
from flask_babel import force_locale, get_locale

# The app's own default (app.config['BABEL_DEFAULT_LOCALE']), used when there is
# no app to ask and no locale to use.
DEFAULT_LOCALE = 'en_GB'


def capture_locale():
    """Return the locale of the current request, or None when there isn't one.

    Call this while the request is still alive and hand the result to
    `translation_scope()` in the thread that needs it.
    """
    try:
        locale = get_locale()
    except Exception:
        return None

    return str(locale) if locale else None


def _usable_locale(app, locale):
    """The locale to force - always one that babel can parse."""
    default = None
    if app is not None:
        default = app.config.get('BABEL_DEFAULT_LOCALE')

    candidate = locale or default or DEFAULT_LOCALE

    try:
        Locale.parse(str(candidate))
    except Exception:
        candidate = default or DEFAULT_LOCALE

    return candidate


@contextmanager
def locale_scope(locale):
    """Run the block with `locale` forced, so gettext() translates into it.

    A locale of None (or an unusable one) leaves the block alone - better to
    return the English string than to raise inside a background thread.
    """
    if not locale:
        yield
        return

    scope = force_locale(str(locale))
    try:
        scope.__enter__()
    except Exception:
        # An unusable locale, or nothing to force it in - leave the block alone.
        yield
        return

    try:
        yield
    finally:
        # Always restore the previous locale, but never swallow an exception
        # raised by the block itself.
        scope.__exit__(None, None, None)


@contextmanager
def translation_scope(app=None, locale=None):
    """Translate into `locale`, inside an application context.

    flask_babel keeps its per-context state on Flask's `g` (which lives in the
    application context) and asks the app's locale selector for the language -
    and that selector needs a *request* (the session / the Accept-Language
    header), which a background thread does not have.

    So: make sure there is an application context to translate in, and always
    force the locale - otherwise gettext() would raise instead of translating.
    """
    if app is not None and not has_app_context():
        with app.app_context():
            with locale_scope(_usable_locale(app, locale)):
                yield
        return

    with locale_scope(_usable_locale(app, locale)):
        yield
