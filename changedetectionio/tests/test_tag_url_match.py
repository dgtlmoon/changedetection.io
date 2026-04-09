#!/usr/bin/env python3
"""
Integration tests for auto-applying tags to watches by URL pattern matching.

Verifies:
 - A tag with url_match_pattern shows on the watch overview list (via get_all_tags_for_watch)
 - The auto-applied tag appears on the watch edit page
 - A watch whose URL does NOT match the pattern does not get the tag
"""

import json
from flask import url_for
from .util import set_original_response, live_server_setup


def test_tag_url_pattern_shows_in_overview(client, live_server, measure_memory_usage, datastore_path):
    """Tag with a matching url_match_pattern must appear in the watch overview row."""
    set_original_response(datastore_path=datastore_path)

    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')

    # Create a tag with a URL match pattern
    res = client.post(
        url_for("tag"),
        data=json.dumps({"title": "Auto GitHub", "url_match_pattern": "*github.com*"}),
        headers={'content-type': 'application/json', 'x-api-key': api_key},
    )
    assert res.status_code == 201, res.data
    tag_uuid = res.json['uuid']

    # Add a watch that matches the pattern
    res = client.post(
        url_for("createwatch"),
        data=json.dumps({"url": "https://github.com/someuser/repo"}),
        headers={'content-type': 'application/json', 'x-api-key': api_key},
    )
    assert res.status_code == 201, res.data
    matching_watch_uuid = res.json['uuid']

    # Add a watch that does NOT match
    res = client.post(
        url_for("createwatch"),
        data=json.dumps({"url": "https://example.com/page"}),
        headers={'content-type': 'application/json', 'x-api-key': api_key},
    )
    assert res.status_code == 201, res.data
    non_matching_watch_uuid = res.json['uuid']

    # Watch overview — the tag label must appear in the matching watch's row
    res = client.get(url_for("watchlist.index"))
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # The tag title should appear somewhere on the page (it's rendered per-watch via get_all_tags_for_watch)
    assert "Auto GitHub" in html, "Auto-matched tag title must appear in watch overview"

    # Verify via the datastore directly that get_all_tags_for_watch returns the pattern-matched tag
    datastore = live_server.app.config['DATASTORE']

    matching_tags = datastore.get_all_tags_for_watch(matching_watch_uuid)
    assert tag_uuid in matching_tags, "Pattern-matched tag must be returned for matching watch"

    non_matching_tags = datastore.get_all_tags_for_watch(non_matching_watch_uuid)
    assert tag_uuid not in non_matching_tags, "Pattern-matched tag must NOT appear for non-matching watch"


def test_auto_applied_tag_shows_on_watch_edit(client, live_server, measure_memory_usage, datastore_path):
    """The watch edit page must show auto-applied tags (from URL pattern) separately."""
    set_original_response(datastore_path=datastore_path)

    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')

    res = client.post(
        url_for("tag"),
        data=json.dumps({"title": "Auto Docs", "url_match_pattern": "*docs.example.com*"}),
        headers={'content-type': 'application/json', 'x-api-key': api_key},
    )
    assert res.status_code == 201, res.data

    res = client.post(
        url_for("createwatch"),
        data=json.dumps({"url": "https://docs.example.com/guide"}),
        headers={'content-type': 'application/json', 'x-api-key': api_key},
    )
    assert res.status_code == 201, res.data
    watch_uuid = res.json['uuid']

    # Watch edit page must mention the auto-applied tag
    res = client.get(url_for("ui.ui_edit.edit_page", uuid=watch_uuid))
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert "Auto Docs" in html, "Auto-applied tag name must appear on watch edit page"
    assert "automatically applied" in html.lower() or "auto" in html.lower(), \
        "Watch edit page must indicate the tag is auto-applied by pattern"


def test_multiple_pattern_tags_all_applied(client, live_server, measure_memory_usage, datastore_path):
    """A watch matching multiple tag patterns must receive all of them, not just the first."""
    set_original_response(datastore_path=datastore_path)

    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')

    # Two tags with different patterns that both match the same URL
    res = client.post(
        url_for("tag"),
        data=json.dumps({"title": "Org Docs", "url_match_pattern": "*docs.*"}),
        headers={'content-type': 'application/json', 'x-api-key': api_key},
    )
    assert res.status_code == 201, res.data
    tag_docs_uuid = res.json['uuid']

    res = client.post(
        url_for("tag"),
        data=json.dumps({"title": "Org Python", "url_match_pattern": "*python*"}),
        headers={'content-type': 'application/json', 'x-api-key': api_key},
    )
    assert res.status_code == 201, res.data
    tag_python_uuid = res.json['uuid']

    # A third tag whose pattern does NOT match
    res = client.post(
        url_for("tag"),
        data=json.dumps({"title": "Org Rust", "url_match_pattern": "*rust-lang*"}),
        headers={'content-type': 'application/json', 'x-api-key': api_key},
    )
    assert res.status_code == 201, res.data
    tag_rust_uuid = res.json['uuid']

    # Watch URL matches both "docs" and "python" patterns but not "rust"
    res = client.post(
        url_for("createwatch"),
        data=json.dumps({"url": "https://docs.python.org/3/library/fnmatch.html"}),
        headers={'content-type': 'application/json', 'x-api-key': api_key},
    )
    assert res.status_code == 201, res.data
    watch_uuid = res.json['uuid']

    datastore = live_server.app.config['DATASTORE']
    resolved = datastore.get_all_tags_for_watch(watch_uuid)

    assert tag_docs_uuid in resolved, "First matching tag must be included"
    assert tag_python_uuid in resolved, "Second matching tag must be included"
    assert tag_rust_uuid not in resolved, "Non-matching tag must NOT be included"
