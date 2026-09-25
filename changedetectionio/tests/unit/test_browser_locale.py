import pytest

from changedetectionio.content_fetchers.base import validate_browser_locale, resolve_browser_locale


@pytest.mark.parametrize('value,expected', [
    ('ja', 'ja'),
    ('ja-JP', 'ja-JP'),
    ('zh-Hant-TW', 'zh-Hant-TW'),
    (' ja-JP ', 'ja-JP'),  # surrounding whitespace is stripped
    ('xx', 'xx'),  # unknown tags are accepted
    ('zz-ZZ', 'zz-ZZ'),
])
def test_valid_browser_locales_accepted(value, expected):
    assert validate_browser_locale(value) == expected


@pytest.mark.parametrize('value', [
    'ja_JP', 'ja;q=0.9', 'j', '日本語', '   ', 123, ['ja'], 'ja-JP\nX-Injected: 1',
])
def test_invalid_browser_locales_rejected(value):
    assert validate_browser_locale(value) is None


@pytest.mark.parametrize('value', ['', None])
def test_empty_browser_locale_treated_as_unset(value):
    assert validate_browser_locale(value) is None


@pytest.mark.parametrize('watch_value,global_value,expected', [
    ('ja-JP', 'de-DE', 'ja-JP'),  # per-watch wins over global
    (None, 'de-DE', 'de-DE'),  # never set falls back to global
    ('', 'de-DE', 'de-DE'),  # blank form submission falls back to global
    ('!!!', 'de-DE', 'de-DE'),  # invalid per-watch value falls back to global
    (None, None, None),  # all unset -> None (legacy behaviour, system default)
])
def test_browser_locale_resolution_order(watch_value, global_value, expected):
    assert resolve_browser_locale(watch_value=watch_value, global_value=global_value) == expected
