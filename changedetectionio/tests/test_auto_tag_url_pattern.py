#!/usr/bin/env python3
"""
Tests for auto-applying tags based on URL pattern matching.
Related to GitHub issue #3454
"""

from flask import url_for

from .util import delete_all_watches, get_UUID_for_tag_name


def test_auto_tag_wildcard_pattern(client, live_server, measure_memory_usage, datastore_path):
    """Test that tags with wildcard patterns are auto-applied to matching URLs"""

    # Create a tag with a wildcard URL pattern
    res = client.post(
        url_for("tags.form_tag_add"),
        data={"name": "github-tag"},
        follow_redirects=True
    )
    assert b"Tag added" in res.data

    tag_uuid = get_UUID_for_tag_name(client, name="github-tag")

    # Set the URL match pattern for the tag
    res = client.post(
        url_for("tags.form_tag_edit_submit", uuid=tag_uuid),
        data={
            "title": "github-tag",
            "url_match_pattern": "*github.com*"
        },
        follow_redirects=True
    )
    assert b"Updated" in res.data

    # Add a watch that should match the pattern
    test_url = "https://github.com/dgtlmoon/changedetection.io"
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": ""},
        follow_redirects=True
    )
    assert b"Watch added" in res.data

    # Verify the tag was auto-applied
    res = client.get(url_for("watchlist.index"))
    assert b'github-tag' in res.data

    # Add a watch that should NOT match the pattern
    test_url_no_match = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url_no_match, "tags": ""},
        follow_redirects=True
    )
    assert b"Watch added" in res.data

    # The non-matching watch should not have the github-tag
    # (We verify by checking the watch edit page)
    watch_uuid = None
    for uuid, watch in live_server.app.config['DATASTORE'].data['watching'].items():
        if watch['url'] == test_url_no_match:
            watch_uuid = uuid
            break

    assert watch_uuid is not None
    watch = live_server.app.config['DATASTORE'].data['watching'][watch_uuid]
    assert tag_uuid not in watch.get('tags', [])

    delete_all_watches(client)
    res = client.get(url_for("tags.delete_all"), follow_redirects=True)


def test_auto_tag_substring_pattern(client, live_server, measure_memory_usage, datastore_path):
    """Test that tags with substring patterns (no wildcards) are auto-applied"""

    # Create a tag with a substring URL pattern
    res = client.post(
        url_for("tags.form_tag_add"),
        data={"name": "example-tag"},
        follow_redirects=True
    )
    assert b"Tag added" in res.data

    tag_uuid = get_UUID_for_tag_name(client, name="example-tag")

    # Set the URL match pattern (substring, no wildcards)
    res = client.post(
        url_for("tags.form_tag_edit_submit", uuid=tag_uuid),
        data={
            "title": "example-tag",
            "url_match_pattern": "example.com"
        },
        follow_redirects=True
    )
    assert b"Updated" in res.data

    # Add a watch that should match the substring
    test_url = "https://www.example.com/page"
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": ""},
        follow_redirects=True
    )
    assert b"Watch added" in res.data

    # Verify the tag was auto-applied
    watch_uuid = None
    for uuid, watch in live_server.app.config['DATASTORE'].data['watching'].items():
        if watch['url'] == test_url:
            watch_uuid = uuid
            break

    assert watch_uuid is not None
    watch = live_server.app.config['DATASTORE'].data['watching'][watch_uuid]
    assert tag_uuid in watch.get('tags', [])

    delete_all_watches(client)
    res = client.get(url_for("tags.delete_all"), follow_redirects=True)


def test_auto_tag_multiple_patterns(client, live_server, measure_memory_usage, datastore_path):
    """Test that multiple tags can be auto-applied to the same URL"""

    # Create first tag
    res = client.post(
        url_for("tags.form_tag_add"),
        data={"name": "tech-news"},
        follow_redirects=True
    )
    assert b"Tag added" in res.data
    tag_uuid_1 = get_UUID_for_tag_name(client, name="tech-news")

    res = client.post(
        url_for("tags.form_tag_edit_submit", uuid=tag_uuid_1),
        data={
            "title": "tech-news",
            "url_match_pattern": "*news*"
        },
        follow_redirects=True
    )

    # Create second tag
    res = client.post(
        url_for("tags.form_tag_add"),
        data={"name": "hacker-news"},
        follow_redirects=True
    )
    assert b"Tag added" in res.data
    tag_uuid_2 = get_UUID_for_tag_name(client, name="hacker-news")

    res = client.post(
        url_for("tags.form_tag_edit_submit", uuid=tag_uuid_2),
        data={
            "title": "hacker-news",
            "url_match_pattern": "*ycombinator*"
        },
        follow_redirects=True
    )

    # Add a watch that matches both patterns
    test_url = "https://news.ycombinator.com/"
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": ""},
        follow_redirects=True
    )
    assert b"Watch added" in res.data

    # Verify both tags were auto-applied
    watch_uuid = None
    for uuid, watch in live_server.app.config['DATASTORE'].data['watching'].items():
        if watch['url'] == test_url:
            watch_uuid = uuid
            break

    assert watch_uuid is not None
    watch = live_server.app.config['DATASTORE'].data['watching'][watch_uuid]
    assert tag_uuid_1 in watch.get('tags', [])
    assert tag_uuid_2 in watch.get('tags', [])

    delete_all_watches(client)
    res = client.get(url_for("tags.delete_all"), follow_redirects=True)


def test_auto_tag_case_insensitive(client, live_server, measure_memory_usage, datastore_path):
    """Test that URL pattern matching is case-insensitive"""

    # Create a tag with uppercase pattern
    res = client.post(
        url_for("tags.form_tag_add"),
        data={"name": "case-test"},
        follow_redirects=True
    )
    assert b"Tag added" in res.data

    tag_uuid = get_UUID_for_tag_name(client, name="case-test")

    res = client.post(
        url_for("tags.form_tag_edit_submit", uuid=tag_uuid),
        data={
            "title": "case-test",
            "url_match_pattern": "*GITHUB.COM*"
        },
        follow_redirects=True
    )
    assert b"Updated" in res.data

    # Add a watch with lowercase URL
    test_url = "https://github.com/test/repo"
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": ""},
        follow_redirects=True
    )
    assert b"Watch added" in res.data

    # Verify the tag was auto-applied despite case difference
    watch_uuid = None
    for uuid, watch in live_server.app.config['DATASTORE'].data['watching'].items():
        if watch['url'] == test_url:
            watch_uuid = uuid
            break

    assert watch_uuid is not None
    watch = live_server.app.config['DATASTORE'].data['watching'][watch_uuid]
    assert tag_uuid in watch.get('tags', [])

    delete_all_watches(client)
    res = client.get(url_for("tags.delete_all"), follow_redirects=True)


def test_auto_tag_empty_pattern_no_match(client, live_server, measure_memory_usage, datastore_path):
    """Test that tags with empty patterns don't auto-apply"""

    # Create a tag without setting a pattern
    res = client.post(
        url_for("tags.form_tag_add"),
        data={"name": "no-pattern-tag"},
        follow_redirects=True
    )
    assert b"Tag added" in res.data

    tag_uuid = get_UUID_for_tag_name(client, name="no-pattern-tag")

    # Add a watch
    test_url = "https://example.com/test"
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": ""},
        follow_redirects=True
    )
    assert b"Watch added" in res.data

    # Verify the tag was NOT auto-applied
    watch_uuid = None
    for uuid, watch in live_server.app.config['DATASTORE'].data['watching'].items():
        if watch['url'] == test_url:
            watch_uuid = uuid
            break

    assert watch_uuid is not None
    watch = live_server.app.config['DATASTORE'].data['watching'][watch_uuid]
    assert tag_uuid not in watch.get('tags', [])

    delete_all_watches(client)
    res = client.get(url_for("tags.delete_all"), follow_redirects=True)
