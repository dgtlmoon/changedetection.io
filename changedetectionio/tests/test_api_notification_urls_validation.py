#!/usr/bin/env python3

"""
Test notification_urls validation in Watch and Tag API endpoints.
Ensures that invalid AppRise URLs are rejected when setting notification_urls.

Valid AppRise notification URLs use specific protocols like:
- posts://example.com - POST to HTTP endpoint
- gets://example.com - GET to HTTP endpoint
- mailto://user@example.com - Email
- slack://token/channel - Slack
- discord://webhook_id/webhook_token - Discord
- etc.

Invalid notification URLs:
- https://example.com - Plain HTTPS is NOT a valid AppRise notification protocol
- ftp://example.com - FTP is NOT a valid AppRise notification protocol
- Plain URLs without proper AppRise protocol prefix
"""

from flask import url_for
import json


def test_watch_notification_urls_validation(client, live_server, measure_memory_usage, datastore_path):
    """Test that Watch PUT/POST endpoints validate notification_urls."""
    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')

    # Test 1: Create a watch with valid notification URLs
    valid_urls = ["posts://example.com/notify1", "posts://example.com/notify2"]
    res = client.post(
        url_for("createwatch"),
        data=json.dumps({
            "url": "https://example.com",
            "notification_urls": valid_urls
        }),
        headers={'content-type': 'application/json', 'x-api-key': api_key}
    )
    assert res.status_code == 201, "Should accept valid notification URLs on watch creation"
    watch_uuid = res.json['uuid']

    # Verify the notification URLs were saved
    res = client.get(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert set(res.json['notification_urls']) == set(valid_urls), "Valid notification URLs should be saved"

    # Test 2: Try to create a watch with invalid notification URLs (https:// is not valid)
    invalid_urls = ["https://example.com/webhook"]
    res = client.post(
        url_for("createwatch"),
        data=json.dumps({
            "url": "https://example.com",
            "notification_urls": invalid_urls
        }),
        headers={'content-type': 'application/json', 'x-api-key': api_key}
    )
    assert res.status_code == 400, "Should reject https:// notification URLs (not a valid AppRise protocol)"
    assert b"is not a valid AppRise URL" in res.data, "Should provide AppRise validation error message"

    # Test 2b: Also test other invalid protocols
    invalid_urls_ftp = ["ftp://not-apprise-url"]
    res = client.post(
        url_for("createwatch"),
        data=json.dumps({
            "url": "https://example.com",
            "notification_urls": invalid_urls_ftp
        }),
        headers={'content-type': 'application/json', 'x-api-key': api_key}
    )
    assert res.status_code == 400, "Should reject ftp:// notification URLs"
    assert b"is not a valid AppRise URL" in res.data, "Should provide AppRise validation error message"

    # Test 3: Update watch with valid notification URLs
    new_valid_urls = ["posts://newserver.com"]
    res = client.put(
        url_for("watch", uuid=watch_uuid),
        data=json.dumps({"notification_urls": new_valid_urls}),
        headers={'content-type': 'application/json', 'x-api-key': api_key}
    )
    assert res.status_code == 200, "Should accept valid notification URLs on watch update"

    # Verify the notification URLs were updated
    res = client.get(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert res.json['notification_urls'] == new_valid_urls, "Valid notification URLs should be updated"

    # Test 4: Try to update watch with invalid notification URLs (plain https:// not valid)
    invalid_https_url = ["https://example.com/webhook"]
    res = client.put(
        url_for("watch", uuid=watch_uuid),
        data=json.dumps({"notification_urls": invalid_https_url}),
        headers={'content-type': 'application/json', 'x-api-key': api_key}
    )
    assert res.status_code == 400, "Should reject https:// notification URLs on watch update"
    assert b"is not a valid AppRise URL" in res.data, "Should provide AppRise validation error message"

    # Test 5: Update watch with non-list notification_urls
    res = client.put(
        url_for("watch", uuid=watch_uuid),
        data=json.dumps({"notification_urls": "not-a-list"}),
        headers={'content-type': 'application/json', 'x-api-key': api_key}
    )
    assert res.status_code == 400, "Should reject non-list notification_urls"
    assert b"notification_urls must be a list" in res.data

    # Test 6: Verify original URLs are preserved after failed update
    res = client.get(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert res.json['notification_urls'] == new_valid_urls, "URLs should remain unchanged after validation failure"


def test_tag_notification_urls_validation(client, live_server, measure_memory_usage, datastore_path):
    """Test that Tag PUT endpoint validates notification_urls."""
    from changedetectionio.model import Tag

    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')
    datastore = live_server.app.config['DATASTORE']

    # Create a tag
    tag_uuid = datastore.add_tag(title="Test Tag")
    assert tag_uuid is not None

    # Test 1: Update tag with valid notification URLs
    valid_urls = ["posts://example.com/tag-notify"]
    res = client.put(
        url_for("tag", uuid=tag_uuid),
        data=json.dumps({"notification_urls": valid_urls}),
        headers={'content-type': 'application/json', 'x-api-key': api_key}
    )
    assert res.status_code == 200, "Should accept valid notification URLs on tag update"

    # Verify the notification URLs were saved
    tag = datastore.data['settings']['application']['tags'][tag_uuid]
    assert tag['notification_urls'] == valid_urls, "Valid notification URLs should be saved to tag"

    # Test 2: Try to update tag with invalid notification URLs (https:// not valid)
    invalid_urls = ["https://example.com/webhook"]
    res = client.put(
        url_for("tag", uuid=tag_uuid),
        data=json.dumps({"notification_urls": invalid_urls}),
        headers={'content-type': 'application/json', 'x-api-key': api_key}
    )
    assert res.status_code == 400, "Should reject https:// notification URLs on tag update"
    assert b"is not a valid AppRise URL" in res.data, "Should provide AppRise validation error message"

    # Test 3: Update tag with non-list notification_urls
    res = client.put(
        url_for("tag", uuid=tag_uuid),
        data=json.dumps({"notification_urls": "not-a-list"}),
        headers={'content-type': 'application/json', 'x-api-key': api_key}
    )
    assert res.status_code == 400, "Should reject non-list notification_urls"
    assert b"notification_urls must be a list" in res.data

    # Test 4: Verify original URLs are preserved after failed update
    tag = datastore.data['settings']['application']['tags'][tag_uuid]
    assert tag['notification_urls'] == valid_urls, "URLs should remain unchanged after validation failure"
