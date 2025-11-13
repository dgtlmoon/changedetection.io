#!/usr/bin/env python3

import time
from flask import url_for
from .util import live_server_setup, wait_for_all_checks, extract_rss_token_from_UI, get_UUID_for_tag_name, delete_all_watches
import os


def set_original_response(datastore_path):
    test_return_data = """<html>
       <body>
     Some initial text<br>
     <p>Watch 1 content</p>
     <p>Watch 2 content</p>
     </body>
     </html>
    """

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)
    return None


def set_modified_response(datastore_path):
    test_return_data = """<html>
       <body>
     Some initial text<br>
     <p>Watch 1 content MODIFIED</p>
     <p>Watch 2 content CHANGED</p>
     </body>
     </html>
    """

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)
    return None


def test_rss_group(client, live_server, measure_memory_usage, datastore_path):
    """
    Test that RSS feed for a specific tag/group shows only watches in that group
    and displays changes correctly.
    """

    set_original_response(datastore_path=datastore_path)

    # Create a tag/group
    res = client.post(
        url_for("tags.form_tag_add"),
        data={"name": "test-rss-group"},
        follow_redirects=True
    )
    assert b"Tag added" in res.data
    assert b"test-rss-group" in res.data

    # Get the tag UUID
    tag_uuid = get_UUID_for_tag_name(client, name="test-rss-group")
    assert tag_uuid is not None

    # Add first watch with the tag
    test_url_1 = url_for('test_endpoint', _external=True) + "?watch=1"
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url_1, "tags": 'test-rss-group'},
        follow_redirects=True
    )
    assert b"Watch added" in res.data

    # Add second watch with the tag
    test_url_2 = url_for('test_endpoint', _external=True) + "?watch=2"
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url_2, "tags": 'test-rss-group'},
        follow_redirects=True
    )
    assert b"Watch added" in res.data

    # Add a third watch WITHOUT the tag (should not appear in RSS)
    test_url_3 = url_for('test_endpoint', _external=True) + "?watch=3"
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url_3, "tags": 'other-tag'},
        follow_redirects=True
    )
    assert b"Watch added" in res.data

    # Wait for initial checks to complete
    wait_for_all_checks(client)

    # Trigger a change
    set_modified_response(datastore_path=datastore_path)

    # Recheck all watches
    res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Get RSS token
    rss_token = extract_rss_token_from_UI(client)
    assert rss_token is not None

    # Request RSS feed for the specific tag/group using the new endpoint
    res = client.get(
        url_for("rss.rss_tag_feed", tag_uuid=tag_uuid, token=rss_token, _external=True),
        follow_redirects=True
    )

    # Verify response is successful
    assert res.status_code == 200
    assert b"<?xml" in res.data or b"<rss" in res.data

    # Verify the RSS feed contains the tag name in the title
    assert b"test-rss-group" in res.data

    # Verify watch 1 and watch 2 are in the RSS feed (they have the tag)
    assert b"watch=1" in res.data
    assert b"watch=2" in res.data

    # Verify watch 3 is NOT in the RSS feed (it doesn't have the tag)
    assert b"watch=3" not in res.data

    # Verify the changes are shown in the RSS feed
    assert b"MODIFIED" in res.data or b"CHANGED" in res.data

    # Verify it's actual RSS/XML format
    assert b"<rss" in res.data or b"<feed" in res.data

    # Test with invalid tag UUID - should return 404
    res = client.get(
        url_for("rss.rss_tag_feed", tag_uuid="invalid-uuid-12345", token=rss_token, _external=True),
        follow_redirects=True
    )
    assert res.status_code == 404
    assert b"not found" in res.data

    # Test with invalid token - should return 403
    res = client.get(
        url_for("rss.rss_tag_feed", tag_uuid=tag_uuid, token="wrong-token", _external=True),
        follow_redirects=True
    )
    assert res.status_code == 403
    assert b"Access denied" in res.data

    # Clean up
    delete_all_watches(client)
    res = client.get(url_for("tags.delete_all"), follow_redirects=True)
    assert b'All tags deleted' in res.data


def test_rss_group_empty_tag(client, live_server, measure_memory_usage, datastore_path):
    """
    Test that RSS feed for a tag with no watches returns valid but empty RSS.
    """

    # Create a tag with no watches
    res = client.post(
        url_for("tags.form_tag_add"),
        data={"name": "empty-tag"},
        follow_redirects=True
    )
    assert b"Tag added" in res.data

    tag_uuid = get_UUID_for_tag_name(client, name="empty-tag")
    assert tag_uuid is not None

    # Get RSS token
    rss_token = extract_rss_token_from_UI(client)

    # Request RSS feed for empty tag
    res = client.get(
        url_for("rss.rss_tag_feed", tag_uuid=tag_uuid, token=rss_token, _external=True),
        follow_redirects=True
    )

    # Should still return 200 with valid RSS
    assert res.status_code == 200
    assert b"<?xml" in res.data or b"<rss" in res.data
    assert b"empty-tag" in res.data

    # Clean up
    res = client.get(url_for("tags.delete_all"), follow_redirects=True)
    assert b'All tags deleted' in res.data


def test_rss_group_only_unviewed(client, live_server, measure_memory_usage, datastore_path):
    """
    Test that RSS feed for a tag only shows unviewed watches.
    """

    set_original_response(datastore_path=datastore_path)

    # Create a tag
    res = client.post(
        url_for("tags.form_tag_add"),
        data={"name": "unviewed-test"},
        follow_redirects=True
    )
    assert b"Tag added" in res.data

    tag_uuid = get_UUID_for_tag_name(client, name="unviewed-test")

    # Add two watches with the tag
    test_url_1 = url_for('test_endpoint', _external=True) + "?unviewed=1"
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url_1, "tags": 'unviewed-test'},
        follow_redirects=True
    )
    assert b"Watch added" in res.data

    test_url_2 = url_for('test_endpoint', _external=True) + "?unviewed=2"
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url_2, "tags": 'unviewed-test'},
        follow_redirects=True
    )
    assert b"Watch added" in res.data

    wait_for_all_checks(client)

    # Trigger changes
    set_modified_response(datastore_path=datastore_path)
    res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Get RSS token
    rss_token = extract_rss_token_from_UI(client)

    # Request RSS feed - should show both watches (both unviewed)
    res = client.get(
        url_for("rss.rss_tag_feed", tag_uuid=tag_uuid, token=rss_token, _external=True),
        follow_redirects=True
    )
    assert res.status_code == 200
    assert b"unviewed=1" in res.data
    assert b"unviewed=2" in res.data

    # Mark all as viewed
    res = client.get(url_for('ui.mark_all_viewed'), follow_redirects=True)
    wait_for_all_checks(client)

    # Request RSS feed again - should be empty now (no unviewed watches)
    res = client.get(
        url_for("rss.rss_tag_feed", tag_uuid=tag_uuid, token=rss_token, _external=True),
        follow_redirects=True
    )
    assert res.status_code == 200
    # Should not contain the watch URLs anymore since they're viewed
    assert b"unviewed=1" not in res.data
    assert b"unviewed=2" not in res.data

    # Clean up
    delete_all_watches(client)
    res = client.get(url_for("tags.delete_all"), follow_redirects=True)
    assert b'All tags deleted' in res.data
