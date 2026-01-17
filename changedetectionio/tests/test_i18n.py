#!/usr/bin/env python3

from flask import url_for
from .util import live_server_setup, wait_for_all_checks


def test_zh_TW(client, live_server, measure_memory_usage, datastore_path):
    import time
    test_url = url_for('test_endpoint', _external=True)

    # Be sure we got a session cookie
    res = client.get(url_for("watchlist.index"), follow_redirects=True)

    res = client.get(
        url_for("set_language", locale="zh_Hant_TW"), # Traditional
        follow_redirects=True
    )
    # HTML follows BCP 47 language tag rules, not underscore-based locale formats.
    assert b'<html lang="zh-Hant-TW"' in res.data
    assert b'Cannot set language without session cookie' not in res.data
    assert '選擇語言'.encode() in res.data

    # Check second set works
    res = client.get(
        url_for("set_language", locale="en_GB"),
        follow_redirects=True
    )
    assert b'Cannot set language without session cookie' not in res.data
    res = client.get(url_for("watchlist.index"), follow_redirects=True)
    assert b"Select Language" in res.data, "Second set of language worked"

    # Check arbitration between zh_Hant_TW<->zh
    res = client.get(
        url_for("set_language", locale="zh"), # Simplified chinese
        follow_redirects=True
    )
    res = client.get(url_for("watchlist.index"), follow_redirects=True)
    assert "选择语言".encode() in res.data, "Simplified chinese worked and it means the flask-babel cache worked"


# timeago library just hasn't been updated to use the more modern locale naming convention, before BCP 47 / RFC 5646.
# The Python timeago library (https://github.com/hustcc/timeago) supports 48 locales but uses different naming conventions than Flask-Babel.
def test_zh_Hant_TW_timeago_integration():
    """Test that zh_Hant_TW mapping works and timeago renders Traditional Chinese correctly"""
    import timeago
    from datetime import datetime, timedelta
    from changedetectionio.languages import get_timeago_locale

    # 1. Test the mapping
    mapped_locale = get_timeago_locale('zh_Hant_TW')
    assert mapped_locale == 'zh_TW', "zh_Hant_TW should map to timeago's zh_TW"
    assert get_timeago_locale('zh_TW') == 'zh_TW', "zh_TW should also map to zh_TW"

    # 2. Test timeago library renders Traditional Chinese with the mapped locale
    now = datetime.now()

    # Test various time periods with Traditional Chinese strings
    result_15s = timeago.format(now - timedelta(seconds=15), now, mapped_locale)
    assert '秒前' in result_15s, f"Expected '秒前' in '{result_15s}'"

    result_5m = timeago.format(now - timedelta(minutes=5), now, mapped_locale)
    assert '分鐘前' in result_5m, f"Expected '分鐘前' in '{result_5m}'"

    result_2h = timeago.format(now - timedelta(hours=2), now, mapped_locale)
    assert '小時前' in result_2h, f"Expected '小時前' in '{result_2h}'"

    result_3d = timeago.format(now - timedelta(days=3), now, mapped_locale)
    assert '天前' in result_3d, f"Expected '天前' in '{result_3d}'"


def test_language_switching(client, live_server, measure_memory_usage, datastore_path):
    """
    Test that the language switching functionality works correctly.

    1. Switch to Italian using the /set-language endpoint
    2. Verify that Italian text appears on the page
    3. Switch back to English and verify English text appears
    """

    # Establish session cookie
    client.get(url_for("watchlist.index"), follow_redirects=True)

    # Step 1: Set the language to Italian using the /set-language endpoint
    res = client.get(
        url_for("set_language", locale="it"),
        follow_redirects=True
    )

    assert res.status_code == 200

    # Step 2: Request the index page - should be in Italian
    # The session cookie should be maintained by the test client
    res = client.get(
        url_for("watchlist.index"),
        follow_redirects=True
    )

    assert res.status_code == 200

    # Check for Italian text - "Annulla" (translation of "Cancel")
    assert b"Annulla" in res.data, "Expected Italian text 'Annulla' not found after setting language to Italian"

    assert b'Modifiche testo/HTML, JSON e PDF' in res.data, "Expected italian from processors.available_processors()"

    # Step 3: Switch back to English
    res = client.get(
        url_for("set_language", locale="en"),
        follow_redirects=True
    )

    assert res.status_code == 200

    # Request the index page - should now be in English
    res = client.get(
        url_for("watchlist.index"),
        follow_redirects=True
    )

    assert res.status_code == 200

    # Check for English text
    assert b"Cancel" in res.data, "Expected English text 'Cancel' not found after switching back to English"


def test_invalid_locale(client, live_server, measure_memory_usage, datastore_path):
    """
    Test that setting an invalid locale doesn't break the application.
    The app should ignore invalid locales and continue working.
    """

    # Establish session cookie
    client.get(url_for("watchlist.index"), follow_redirects=True)

    # First set to English
    res = client.get(
        url_for("set_language", locale="en"),
        follow_redirects=True
    )

    assert res.status_code == 200

    # Try to set an invalid locale
    res = client.get(
        url_for("set_language", locale="invalid_locale_xyz"),
        follow_redirects=True
    )

    assert res.status_code == 200

    # Should still be able to access the page (should stay in English since invalid locale was ignored)
    res = client.get(
        url_for("watchlist.index"),
        follow_redirects=True
    )

    assert res.status_code == 200
    assert b"Cancel" in res.data, "Should remain in English when invalid locale is provided"


def test_language_persistence_in_session(client, live_server, measure_memory_usage, datastore_path):
    """
    Test that the language preference persists across multiple requests
    within the same session.
    """

    # Establish session cookie
    client.get(url_for("watchlist.index"), follow_redirects=True)

    # Set language to Italian
    res = client.get(
        url_for("set_language", locale="it"),
        follow_redirects=True
    )

    assert res.status_code == 200

    # Make multiple requests - language should persist
    for _ in range(3):
        res = client.get(
            url_for("watchlist.index"),
            follow_redirects=True
        )

        assert res.status_code == 200
        assert b"Annulla" in res.data, "Italian text should persist across requests"


def test_set_language_with_redirect(client, live_server, measure_memory_usage, datastore_path):
    """
    Test that changing language keeps the user on the same page.
    Example: User is on /settings, changes language, stays on /settings.
    """
    from flask import url_for

    # Establish session cookie
    client.get(url_for("watchlist.index"), follow_redirects=True)

    # Set language with a redirect parameter (simulating language change from /settings)
    res = client.get(
        url_for("set_language", locale="de", redirect="/settings"),
        follow_redirects=False
    )

    # Should redirect back to settings
    assert res.status_code in [302, 303]
    assert '/settings' in res.location

    # Verify language was set in session
    with client.session_transaction() as sess:
        assert sess.get('locale') == 'de'

    # Test with invalid locale (should still redirect safely)
    res = client.get(
        url_for("set_language", locale="invalid_locale", redirect="/settings"),
        follow_redirects=False
    )
    assert res.status_code in [302, 303]
    assert '/settings' in res.location

    # Test with malicious redirect (should default to watchlist)
    res = client.get(
        url_for("set_language", locale="en", redirect="https://evil.com"),
        follow_redirects=False
    )
    assert res.status_code in [302, 303]
    # Should not redirect to evil.com
    assert 'evil.com' not in res.location


def test_time_unit_translations(client, live_server, measure_memory_usage, datastore_path):
    """
    Test that time unit labels (Hours, Minutes, Seconds) and Chrome Extension
    are correctly translated on the settings page for all supported languages.
    """
    from flask import url_for

    # Establish session cookie
    client.get(url_for("watchlist.index"), follow_redirects=True)

    # Test Italian translations
    res = client.get(url_for("set_language", locale="it"), follow_redirects=True)
    assert res.status_code == 200

    res = client.get(url_for("settings.settings_page"), follow_redirects=True)
    assert res.status_code == 200

    # Check that Italian translations are present (not English)
    assert b"Minutes" not in res.data or b"Minuti" in res.data, "Expected Italian 'Minuti' not English 'Minutes'"
    assert b"Ore" in res.data, "Expected Italian 'Ore' for Hours"
    assert b"Minuti" in res.data, "Expected Italian 'Minuti' for Minutes"
    assert b"Secondi" in res.data, "Expected Italian 'Secondi' for Seconds"
    assert b"Estensione Chrome" in res.data, "Expected Italian 'Estensione Chrome' for Chrome Extension"
    assert b"Intervallo tra controlli" in res.data, "Expected Italian 'Intervallo tra controlli' for Time Between Check"
    assert b"Time Between Check" not in res.data, "Should not have English 'Time Between Check'"

    # Test Korean translations
    res = client.get(url_for("set_language", locale="ko"), follow_redirects=True)
    assert res.status_code == 200

    res = client.get(url_for("settings.settings_page"), follow_redirects=True)
    assert res.status_code == 200

    # Check that Korean translations are present (not English)
    # Korean: Hours=시간, Minutes=분, Seconds=초, Chrome Extension=Chrome 확장 프로그램, Time Between Check=확인 간격
    assert "시간".encode() in res.data, "Expected Korean '시간' for Hours"
    assert "분".encode() in res.data, "Expected Korean '분' for Minutes"
    assert "초".encode() in res.data, "Expected Korean '초' for Seconds"
    assert "Chrome 확장 프로그램".encode() in res.data, "Expected Korean 'Chrome 확장 프로그램' for Chrome Extension"
    assert "확인 간격".encode() in res.data, "Expected Korean '확인 간격' for Time Between Check"
    # Make sure we don't have the incorrect translations
    assert "목요일".encode() not in res.data, "Should not have '목요일' (Thursday) for Hours"
    assert "무음".encode() not in res.data, "Should not have '무음' (Mute) for Minutes"
    assert "Chrome 요청".encode() not in res.data, "Should not have 'Chrome 요청' (Chrome requests) for Chrome Extension"
    assert b"Time Between Check" not in res.data, "Should not have English 'Time Between Check'"

    # Test Chinese Simplified translations
    res = client.get(url_for("set_language", locale="zh"), follow_redirects=True)
    assert res.status_code == 200

    res = client.get(url_for("settings.settings_page"), follow_redirects=True)
    assert res.status_code == 200

    # Check that Chinese translations are present
    # Chinese: Hours=小时, Minutes=分钟, Seconds=秒, Chrome Extension=Chrome 扩展程序, Time Between Check=检查间隔
    assert "小时".encode() in res.data, "Expected Chinese '小时' for Hours"
    assert "分钟".encode() in res.data, "Expected Chinese '分钟' for Minutes"
    assert "秒".encode() in res.data, "Expected Chinese '秒' for Seconds"
    assert "Chrome 扩展程序".encode() in res.data, "Expected Chinese 'Chrome 扩展程序' for Chrome Extension"
    assert "检查间隔".encode() in res.data, "Expected Chinese '检查间隔' for Time Between Check"
    assert b"Time Between Check" not in res.data, "Should not have English 'Time Between Check'"

    # Test German translations
    res = client.get(url_for("set_language", locale="de"), follow_redirects=True)
    assert res.status_code == 200

    res = client.get(url_for("settings.settings_page"), follow_redirects=True)
    assert res.status_code == 200

    # Check that German translations are present
    # German: Hours=Stunden, Minutes=Minuten, Seconds=Sekunden, Chrome Extension=Chrome-Erweiterung, Time Between Check=Prüfintervall
    assert b"Stunden" in res.data, "Expected German 'Stunden' for Hours"
    assert b"Minuten" in res.data, "Expected German 'Minuten' for Minutes"
    assert b"Sekunden" in res.data, "Expected German 'Sekunden' for Seconds"
    assert b"Chrome-Erweiterung" in res.data, "Expected German 'Chrome-Erweiterung' for Chrome Extension"
    assert b"Time Between Check" not in res.data, "Should not have English 'Time Between Check'"

    # Test Traditional Chinese (zh_Hant_TW) translations
    res = client.get(url_for("set_language", locale="zh_Hant_TW"), follow_redirects=True)
    assert res.status_code == 200

    res = client.get(url_for("settings.settings_page"), follow_redirects=True)
    assert res.status_code == 200

    # Check that Traditional Chinese translations are present (not English)
    # Traditional Chinese: Hours=小時, Minutes=分鐘, Seconds=秒, Chrome Extension=Chrome 擴充功能, Time Between Check=檢查間隔
    assert "小時".encode() in res.data, "Expected Traditional Chinese '小時' for Hours"
    assert "分鐘".encode() in res.data, "Expected Traditional Chinese '分鐘' for Minutes"
    assert "秒".encode() in res.data, "Expected Traditional Chinese '秒' for Seconds"
    assert "Chrome 擴充功能".encode() in res.data, "Expected Traditional Chinese 'Chrome 擴充功能' for Chrome Extension"
    assert "發送測試通知".encode() in res.data, "Expected Traditional Chinese '發送測試通知' for Send test notification"
    assert "通知除錯記錄".encode() in res.data, "Expected Traditional Chinese '通知除錯記錄' for Notification debug logs"
    assert "檢查間隔".encode() in res.data, "Expected Traditional Chinese '檢查間隔' for Time Between Check"
    # Make sure we don't have incorrect English text or wrong translations
    assert b"Send test notification" not in res.data, "Should not have English 'Send test notification'"
    assert b"Time Between Check" not in res.data, "Should not have English 'Time Between Check'"
    assert "Chrome 請求".encode() not in res.data, "Should not have incorrect 'Chrome 請求' (Chrome requests)"
    assert "使用預設通知".encode() not in res.data, "Should not have incorrect '使用預設通知' (Use default notification)"
