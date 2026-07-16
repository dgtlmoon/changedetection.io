"""
Language configuration for i18n support
Automatically discovers available languages from translations directory
"""
import os
from pathlib import Path


def get_timeago_locale(flask_locale, short=False):
    """
    Convert Flask-Babel locale codes to timeago library locale codes.

    The Python timeago library (https://github.com/hustcc/timeago) supports 48 locales
    but uses different naming conventions than Flask-Babel. This function maps between them.

    Notable differences:
    - Chinese: Flask uses 'zh', timeago uses 'zh_CN'
    - Portuguese: Flask uses 'pt', timeago uses 'pt_PT' or 'pt_BR'
    - Swedish: Flask uses 'sv', timeago uses 'sv_SE'
    - Norwegian: Flask uses 'no', timeago uses 'nb_NO' or 'nn_NO'
    - Hindi: Flask uses 'hi', timeago uses 'in_HI'
    - Czech: Flask uses 'cs', but timeago doesn't support Czech - fallback to English

    Args:
        flask_locale (str): Flask-Babel locale code (e.g., 'cs', 'zh', 'pt')
        short (bool): Return a compact "1m ago" style locale instead of "1 minute ago".
                      timeago only ships 'en_short'; the other short locales are registered
                      by register_short_timeago_locales() below. Unsupported languages fall
                      back to 'en_short' so short mode is always honoured.

    Returns:
        str: timeago library locale code (e.g., 'en', 'zh_CN', 'pt_PT', 'de_short')
    """
    if short:
        # Short forms are translated through the normal gettext (.po/.mo) workflow rather than
        # timeago's bundled per-language tables; build + register the table for this locale.
        return register_short_timeago_locale(flask_locale)

    locale_map = {
        'zh': 'zh_CN',          # Chinese Simplified
        # timeago library just hasn't been updated to use the more modern locale naming convention, before BCP 47 / RFC 5646.
        'zh_TW': 'zh_TW',       # Chinese Traditional (timeago uses zh_TW)
        'zh_Hant_TW': 'zh_TW',  # Flask-Babel normalizes zh_TW to zh_Hant_TW, map back to timeago's zh_TW
        'pt': 'pt_PT',          # Portuguese (Portugal)
        'pt_BR': 'pt_BR',       # Portuguese (Brasil)
        'sv': 'sv_SE',          # Swedish
        'no': 'nb_NO',          # Norwegian Bokmål
        'hi': 'in_HI',          # Hindi
        'cs': 'en',             # Czech not supported by timeago, fallback to English
        'ja': 'ja',             # Japanese
        'uk': 'uk',             # Ukrainian
        'en_GB': 'en',          # British English - timeago uses 'en'
        'en_US': 'en',          # American English - timeago uses 'en'
    }
    return locale_map.get(flask_locale, flask_locale)


# --- Short ("1m ago") timeago locales -------------------------------------------------
#
# timeago only ships 'en_short' and resolves a locale by name via
# __import__('timeago.locales.<name>'), which checks sys.modules first. So we register a table
# at runtime per locale. Rather than hard-code a table per language, the short strings are
# routed through the normal gettext (.po/.mo) workflow: the rows below are wrapped in
# lazy_gettext (_l) so `python setup.py extract_messages` picks them up, and they resolve to
# the active locale when rendered. Translators maintain the short forms in messages.po just
# like every other string.
#
# 14 rows of (past, future) following timeago's index order:
#   now, Ns, 1m, Nm, 1h, Nh, 1d, Nd, 1w, Nw, 1mo, Nmo, 1yr, Nyr   ('%s' = the number)
# The English source strings double as the gettext msgids.

def _build_short_timeago_rows():
    from flask_babel import lazy_gettext as _l
    return [
        (_l('just now'), _l('right now')),
        (_l('%ss ago'),  _l('in %ss')),
        (_l('1m ago'),   _l('in 1m')),
        (_l('%sm ago'),  _l('in %sm')),
        (_l('1h ago'),   _l('in 1h')),
        (_l('%sh ago'),  _l('in %sh')),
        (_l('1d ago'),   _l('in 1d')),
        (_l('%sd ago'),  _l('in %sd')),
        (_l('1w ago'),   _l('in 1w')),
        (_l('%sw ago'),  _l('in %sw')),
        (_l('1mo ago'),  _l('in 1mo')),
        (_l('%smo ago'), _l('in %smo')),
        (_l('1yr ago'),  _l('in 1yr')),
        (_l('%syr ago'), _l('in %syr')),
    ]


_short_timeago_rows = None
_registered_short_locales = set()


def register_short_timeago_locale(flask_locale):
    """
    Build the short timeago table for `flask_locale` from the gettext catalog and register it
    under a synthetic name so timeago.format(..., <name>) can use it. Returns the locale name
    to hand to timeago (falls back to the bundled 'en_short' if anything goes wrong).

    The table is resolved with flask_babel.force_locale so it is correct regardless of which
    locale is active, and cached per language so the gettext lookups happen only once each.
    """
    name = 'cd_short_' + str(flask_locale).replace('-', '_')
    if name in _registered_short_locales:
        return name

    try:
        import sys
        import types
        import timeago.locales as timeago_locales
        from flask_babel import force_locale

        global _short_timeago_rows
        if _short_timeago_rows is None:
            _short_timeago_rows = _build_short_timeago_rows()

        with force_locale(str(flask_locale)):
            table = [[str(past), str(future)] for past, future in _short_timeago_rows]

        mod_name = 'timeago.locales.' + name
        mod = types.ModuleType(mod_name)
        mod.LOCALE = table
        sys.modules[mod_name] = mod
        setattr(timeago_locales, name, mod)
        _registered_short_locales.add(name)
        return name
    except Exception:
        # Outside an app context, or any unexpected failure -> bundled English short locale.
        return 'en_short'

# Language metadata: flag icon CSS class and native name
# Using flag-icons library: https://flagicons.lipis.dev/
LANGUAGE_DATA = {
    'en_GB': {'flag': 'fi fi-gb fis', 'name': 'English (UK)'},
    'en_US': {'flag': 'fi fi-us fis', 'name': 'English (US)'},
    'de': {'flag': 'fi fi-de fis', 'name': 'Deutsch'},
    'fr': {'flag': 'fi fi-fr fis', 'name': 'Français'},
    'ko': {'flag': 'fi fi-kr fis', 'name': '한국어'},
    'cs': {'flag': 'fi fi-cz fis', 'name': 'Čeština'},
    'es': {'flag': 'fi fi-es fis', 'name': 'Español'},
    'pt': {'flag': 'fi fi-pt fis', 'name': 'Português (Portugal)'},
    'pt_BR': {'flag': 'fi fi-br fis', 'name': 'Português (Brasil)'},
    'it': {'flag': 'fi fi-it fis', 'name': 'Italiano'},
    'ja': {'flag': 'fi fi-jp fis', 'name': '日本語'},
    'zh': {'flag': 'fi fi-cn fis', 'name': '中文 (简体)'},
    'zh_Hant_TW': {'flag': 'fi fi-tw fis', 'name': '繁體中文'},
    'ru': {'flag': 'fi fi-ru fis', 'name': 'Русский'},
    'pl': {'flag': 'fi fi-pl fis', 'name': 'Polski'},
    'nl': {'flag': 'fi fi-nl fis', 'name': 'Nederlands'},
    'sv': {'flag': 'fi fi-se fis', 'name': 'Svenska'},
    'da': {'flag': 'fi fi-dk fis', 'name': 'Dansk'},
    'no': {'flag': 'fi fi-no fis', 'name': 'Norsk'},
    'fi': {'flag': 'fi fi-fi fis', 'name': 'Suomi'},
    'tr': {'flag': 'fi fi-tr fis', 'name': 'Türkçe'},
    'ar': {'flag': 'fi fi-sa fis', 'name': 'العربية'},
    'hi': {'flag': 'fi fi-in fis', 'name': 'हिन्दी'},
    'uk': {'flag': 'fi fi-ua fis', 'name': 'Українська'},
}


def get_available_languages():
    """
    Discover available languages by scanning the translations directory
    Returns a dict of available languages with their metadata
    """
    translations_dir = Path(__file__).parent / 'translations'

    available = {}

    # Scan for translation directories
    if translations_dir.exists():
        for lang_dir in translations_dir.iterdir():
            if lang_dir.is_dir() and lang_dir.name in LANGUAGE_DATA:
                # Check if messages.po exists
                po_file = lang_dir / 'LC_MESSAGES' / 'messages.po'
                if po_file.exists():
                    available[lang_dir.name] = LANGUAGE_DATA[lang_dir.name]

    # If no English variants found, fall back to adding en_GB as default
    if 'en_GB' not in available and 'en_US' not in available:
        available['en_GB'] = LANGUAGE_DATA['en_GB']

    return available


def get_language_codes():
    """Get list of available language codes"""
    return list(get_available_languages().keys())


def get_flag_for_locale(locale):
    """Get flag emoji for a locale, or globe if unknown"""
    return LANGUAGE_DATA.get(locale, {}).get('flag', '🌐')


def get_name_for_locale(locale):
    """Get native name for a locale"""
    return LANGUAGE_DATA.get(locale, {}).get('name', locale.upper())
