"""
Language configuration for i18n support
Automatically discovers available languages from translations directory
"""
import os
from pathlib import Path


def get_timeago_locale(flask_locale):
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

    Returns:
        str: timeago library locale code (e.g., 'en', 'zh_CN', 'pt_PT')
    """
    locale_map = {
        'zh': 'zh_CN',      # Chinese Simplified
        'zh_Hant_TW': 'zh_TW',  # Flask-Babel normalizes zh_TW to zh_Hant_TW
        'pt': 'pt_PT',      # Portuguese (Portugal)
        'sv': 'sv_SE',      # Swedish
        'no': 'nb_NO',      # Norwegian Bokmål
        'hi': 'in_HI',      # Hindi
        'cs': 'en',         # Czech not supported by timeago, fallback to English
        'en_GB': 'en',      # British English - timeago uses 'en'
        'en_US': 'en',      # American English - timeago uses 'en'
    }
    return locale_map.get(flask_locale, flask_locale)

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
    'pt': {'flag': 'fi fi-pt fis', 'name': 'Português'},
    'it': {'flag': 'fi fi-it fis', 'name': 'Italiano'},
    'ja': {'flag': 'fi fi-jp fis', 'name': '日本語'},
    'zh': {'flag': 'fi fi-cn fis', 'name': '中文 (简体)'},
    'zh_TW': {'flag': 'fi fi-tw fis', 'name': '繁體中文'},
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
