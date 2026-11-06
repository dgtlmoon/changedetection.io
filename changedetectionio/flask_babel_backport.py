"""Backport of python-babel/flask-babel#241 for Flask-Babel 4.0.0.

https://github.com/python-babel/flask-babel/pull/241

When the translation overlay has no catalog for the locale,
ngettext falls back to English. Fixed in Flask-Babel 4.1.0.

NOTE: `get_translations()` below is copied verbatim from v4.1.0; do not edit.
Once Flask-Babel 4.1.0+ is on PyPI, delete this module, switch back to
flask_babel.Babel, and remove the `<4.1.0` upper bound in requirements.txt.

Source:
https://github.com/python-babel/flask-babel/blob/v4.1.0/flask_babel/__init__.py
Copyright (c) 2010 by Armin Ronacher.
Copyright (c) 2013 by Armin Ronacher, Daniel Neuhäuser.
License: BSD-3-Clause (https://github.com/python-babel/flask-babel/blob/v4.1.0/LICENSE)
"""

from werkzeug.utils import cached_property

from babel import support
from flask_babel import Babel, Domain, _get_current_context, get_locale


class DomainWithPluralBackport(Domain):
    # --- begin verbatim copy from Flask-Babel v4.1.0 ---
    def get_translations(self):
        ctx = _get_current_context()

        if ctx is None:
            return support.NullTranslations()

        cache = self.get_translations_cache(ctx)
        locale = get_locale()
        try:
            return cache[str(locale), self.domain[0]]
        except KeyError:
            translations = support.Translations()

            for index, dirname in enumerate(self.translation_directories):

                domain = self.domain[0] if len(self.domain) == 1 else self.domain[index]

                catalog = support.Translations.load(dirname, [locale], domain)
                translations.merge(catalog)
                # FIXME: Workaround for merge() being really, really stupid. It
                # does not copy _info, plural(), or any other instance variables
                # populated by GNUTranslations. We probably want to stop using
                # `support.Translations.merge` entirely.
                if catalog.info() and hasattr(catalog, "plural"):
                    translations.plural = catalog.plural

            cache[str(locale), self.domain[0]] = translations
            return translations
    # --- end verbatim copy ---


class BabelWithPluralBackport(Babel):
    @cached_property
    def domain_instance(self):
        return DomainWithPluralBackport(domain=self.domain)
