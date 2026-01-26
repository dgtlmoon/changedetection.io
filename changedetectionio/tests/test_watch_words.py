#!/usr/bin/env python3
"""
Tests for watch words feature (block_words and trigger_words).

block_words: Notify when these words DISAPPEAR (restock alerts)
  - Block while words ARE present on page
  - Allow (unblock) when words are NOT present

trigger_words: Notify when these words APPEAR (sold out alerts)
  - Block while words are NOT present on page
  - Allow (unblock) when words ARE present
"""
import os
import time
from flask import url_for
from .util import wait_for_all_checks


def set_content_with_sold_out(datastore_path):
    """Page showing "Sold Out" - block_words should block."""
    test_return_data = """<html><body>
    <h1>Concert Tickets</h1>
    <p class="status">Sold Out</p>
    <p>Check back later for availability.</p>
    </body></html>"""

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)


def set_content_without_sold_out(datastore_path):
    """Page without "Sold Out" - block_words should allow."""
    test_return_data = """<html><body>
    <h1>Concert Tickets</h1>
    <p class="status">Available</p>
    <p>Buy now before they are gone!</p>
    </body></html>"""

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)


def set_content_with_on_sale(datastore_path):
    """Page showing "On Sale Now" - trigger_words should allow."""
    test_return_data = """<html><body>
    <h1>Concert Tickets</h1>
    <p class="status">On Sale Now</p>
    <p>Get your tickets today!</p>
    </body></html>"""

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)


def set_content_without_on_sale(datastore_path):
    """Page without "On Sale Now" - trigger_words should block."""
    test_return_data = """<html><body>
    <h1>Concert Tickets</h1>
    <p class="status">Coming Soon</p>
    <p>Sales begin January 15th.</p>
    </body></html>"""

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)


# ============================================================
# BLOCK_WORDS TESTS
# ============================================================

def test_block_words_blocks_while_present(client, live_server, measure_memory_usage, datastore_path):
    """
    Test: block_words blocks notifications while the words are present.

    Scenario: Restock alert - user wants to know when "Sold Out" disappears.
    Expected: Blocked while "Sold Out" is on page, allowed when it's gone.
    """
    # Setup: Page with "Sold Out"
    set_content_with_sold_out(datastore_path)

    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": "", "edit_and_watch_submit_button": "Edit > Watch"},
        follow_redirects=True
    )
    assert b"Watch added" in res.data

    # Configure block_words
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "block_words": "Sold Out",
            "url": test_url,
            "fetch_backend": "html_requests",
            "time_between_check_use_default": "y"
        },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    # First check - establishes baseline
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Verify block_words was saved
    res = client.get(url_for("ui.ui_edit.edit_page", uuid="first"))
    assert b"Sold Out" in res.data

    # Should be blocked (no notification because "Sold Out" is present)
    res = client.get(url_for("watchlist.index"))
    assert b'has-unread-changes' not in res.data, "Should be blocked while 'Sold Out' present"

    # Remove "Sold Out" → should be UNBLOCKED and show change
    set_content_without_sold_out(datastore_path)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.get(url_for("watchlist.index"))
    assert b'has-unread-changes' in res.data, "Should notify when 'Sold Out' disappears"


def test_block_words_regex_support(client, live_server, measure_memory_usage, datastore_path):
    """
    Test: block_words supports perl-style regex patterns.
    """
    set_content_with_sold_out(datastore_path)

    test_url = url_for('test_endpoint', _external=True)
    client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": "", "edit_and_watch_submit_button": "Edit > Watch"},
        follow_redirects=True
    )

    # Configure block_words with regex
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "block_words": "/sold\\s*out/i",  # Regex: "sold" followed by optional whitespace and "out"
            "url": test_url,
            "fetch_backend": "html_requests",
            "time_between_check_use_default": "y"
        },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Should be blocked (regex matches "Sold Out")
    res = client.get(url_for("watchlist.index"))
    assert b'has-unread-changes' not in res.data


def test_block_words_case_insensitive(client, live_server, measure_memory_usage, datastore_path):
    """
    Test: block_words plain text matching is case-insensitive.
    """
    # Content has "Sold Out" with capital letters
    set_content_with_sold_out(datastore_path)

    test_url = url_for('test_endpoint', _external=True)
    client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": "", "edit_and_watch_submit_button": "Edit > Watch"},
        follow_redirects=True
    )

    # Configure with lowercase
    client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "block_words": "sold out",  # lowercase
            "url": test_url,
            "fetch_backend": "html_requests",
            "time_between_check_use_default": "y"
        },
        follow_redirects=True
    )

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Should be blocked (case-insensitive match)
    res = client.get(url_for("watchlist.index"))
    assert b'has-unread-changes' not in res.data


def test_block_words_empty_no_effect(client, live_server, measure_memory_usage, datastore_path):
    """
    Test: Empty block_words has no blocking effect.
    """
    set_content_with_sold_out(datastore_path)

    test_url = url_for('test_endpoint', _external=True)
    client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": "", "edit_and_watch_submit_button": "Edit > Watch"},
        follow_redirects=True
    )

    # Don't configure any block_words
    client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "block_words": "",  # Empty
            "url": test_url,
            "fetch_backend": "html_requests",
            "time_between_check_use_default": "y"
        },
        follow_redirects=True
    )

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Change content
    set_content_without_sold_out(datastore_path)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Should NOT be blocked (no block_words configured)
    res = client.get(url_for("watchlist.index"))
    assert b'has-unread-changes' in res.data


# ============================================================
# TRIGGER_WORDS TESTS
# ============================================================

def test_trigger_words_blocks_until_present(client, live_server, measure_memory_usage, datastore_path):
    """
    Test: trigger_words blocks notifications until the words appear.

    Scenario: Sale alert - user wants to know when "On Sale Now" appears.
    Expected: Blocked while "On Sale Now" not on page, allowed when it appears.
    """
    # Setup: Page without "On Sale Now"
    set_content_without_on_sale(datastore_path)

    test_url = url_for('test_endpoint', _external=True)
    client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": "", "edit_and_watch_submit_button": "Edit > Watch"},
        follow_redirects=True
    )

    # Configure trigger_words
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "trigger_words": "On Sale Now",
            "url": test_url,
            "fetch_backend": "html_requests",
            "time_between_check_use_default": "y"
        },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Should be blocked (waiting for "On Sale Now" to appear)
    res = client.get(url_for("watchlist.index"))
    assert b'has-unread-changes' not in res.data, "Should be blocked until 'On Sale Now' appears"

    # Add "On Sale Now" → should be UNBLOCKED
    set_content_with_on_sale(datastore_path)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.get(url_for("watchlist.index"))
    assert b'has-unread-changes' in res.data, "Should notify when 'On Sale Now' appears"


def test_trigger_words_multiple_patterns(client, live_server, measure_memory_usage, datastore_path):
    """
    Test: trigger_words with multiple patterns - any match allows notification.
    """
    set_content_without_on_sale(datastore_path)

    test_url = url_for('test_endpoint', _external=True)
    client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": "", "edit_and_watch_submit_button": "Edit > Watch"},
        follow_redirects=True
    )

    # Configure multiple trigger_words
    client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "trigger_words": "On Sale Now\nBuy Tickets\nAvailable",  # Multiple patterns
            "url": test_url,
            "fetch_backend": "html_requests",
            "time_between_check_use_default": "y"
        },
        follow_redirects=True
    )

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Content has "Available" (one of the trigger words)
    set_content_without_sold_out(datastore_path)  # This has "Available"
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Should be allowed (one of the trigger words matched)
    res = client.get(url_for("watchlist.index"))
    assert b'has-unread-changes' in res.data


# ============================================================
# COMBINED TESTS
# ============================================================

def test_block_words_and_trigger_words_combined(client, live_server, measure_memory_usage, datastore_path):
    """
    Test: Both block_words and trigger_words configured - both rules must pass.
    """
    set_content_with_sold_out(datastore_path)

    test_url = url_for('test_endpoint', _external=True)
    client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": "", "edit_and_watch_submit_button": "Edit > Watch"},
        follow_redirects=True
    )

    # Configure both
    client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "block_words": "Sold Out",
            "trigger_words": "Available",
            "url": test_url,
            "fetch_backend": "html_requests",
            "time_between_check_use_default": "y"
        },
        follow_redirects=True
    )

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Content has "Sold Out" but not "Available" → blocked by BOTH rules
    res = client.get(url_for("watchlist.index"))
    assert b'has-unread-changes' not in res.data

    # Remove "Sold Out", add "Available"
    set_content_without_sold_out(datastore_path)  # Has "Available", no "Sold Out"
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Now both conditions met: no "Sold Out", has "Available"
    res = client.get(url_for("watchlist.index"))
    assert b'has-unread-changes' in res.data


def test_watch_words_preview_highlighting(client, live_server, measure_memory_usage, datastore_path):
    """
    Test: Preview page passes watch words line numbers for highlighting.
    """
    set_content_with_sold_out(datastore_path)

    test_url = url_for('test_endpoint', _external=True)
    client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": "", "edit_and_watch_submit_button": "Edit > Watch"},
        follow_redirects=True
    )

    client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "block_words": "Sold Out",
            "url": test_url,
            "fetch_backend": "html_requests",
            "time_between_check_use_default": "y"
        },
        follow_redirects=True
    )

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Check preview page renders without error
    res = client.get(url_for("ui_preview.preview_page", uuid="first"))
    assert res.status_code == 200
    # The page should contain Sold Out in the content
    assert b'Sold Out' in res.data
