#!/usr/bin/env python3

from flask import url_for
from .util import live_server_setup


def test_language_switching(client, live_server, measure_memory_usage, datastore_path):
    """
    Test that the language switching functionality works correctly.

    1. Switch to Italian using the /set-language endpoint
    2. Verify that Italian text appears on the page
    3. Switch back to English and verify English text appears
    """

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
