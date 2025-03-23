#!/usr/bin/env python3

import time
from flask import url_for
from .util import live_server_setup, wait_for_all_checks

import json
import uuid


def is_valid_uuid(val):
    try:
        uuid.UUID(str(val))
        return True
    except ValueError:
        return False


def test_setup(client, live_server, measure_memory_usage):
    live_server_setup(live_server)


def test_api_tags(client, live_server, measure_memory_usage):
    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')

    # Make sure we start with no tags
    res = client.get(
        url_for("tags.tags_overview_page")
    )
    assert b'No tags' in res.data

    # Create a tag via API
    res = client.post(
        "/api/v1/tag",
        data=json.dumps({"title": "Test Tag"}),
        headers={'content-type': 'application/json', 'x-api-key': api_key},
        follow_redirects=True
    )

    assert res.status_code == 201
    assert is_valid_uuid(res.json.get('uuid'))
    tag_uuid = res.json.get('uuid')

    # List tags - should include our new tag
    res = client.get(
        "/api/v1/tag",
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert tag_uuid in res.json
    assert res.json[tag_uuid]['title'] == 'Test Tag'
    assert res.json[tag_uuid]['notification_muted'] == False

    # Get single tag
    res = client.get(
        f"/api/v1/tag/{tag_uuid}",
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert res.json['title'] == 'Test Tag'

    # Update tag
    res = client.put(
        f"/api/v1/tag/{tag_uuid}",
        data=json.dumps({"title": "Updated Tag"}),
        headers={'content-type': 'application/json', 'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert b'OK' in res.data

    # Verify update worked
    res = client.get(
        f"/api/v1/tag/{tag_uuid}",
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert res.json['title'] == 'Updated Tag'

    # Mute tag notifications
    res = client.get(
        f"/api/v1/tag/{tag_uuid}?muted=muted",
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert b'OK' in res.data

    # Verify muted status
    res = client.get(
        f"/api/v1/tag/{tag_uuid}",
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert res.json['notification_muted'] == True

    # Unmute tag
    res = client.get(
        f"/api/v1/tag/{tag_uuid}?muted=unmuted",
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert b'OK' in res.data

    # Verify unmuted status
    res = client.get(
        f"/api/v1/tag/{tag_uuid}",
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert res.json['notification_muted'] == False

    # Create a watch with the tag
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        "/api/v1/watch",
        data=json.dumps({"url": test_url, "tag": "Updated Tag", "title": "Watch with tag"}),
        headers={'content-type': 'application/json', 'x-api-key': api_key},
        follow_redirects=True
    )
    assert res.status_code == 201
    watch_uuid = res.json.get('uuid')

    # Verify tag is associated with watch
    res = client.get(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert tag_uuid in res.json.get('tags', [])

    # Delete tag
    res = client.delete(
        f"/api/v1/tag/{tag_uuid}",
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 204

    # Verify tag is gone
    res = client.get(
        "/api/v1/tag",
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert tag_uuid not in res.json

    # Verify tag was removed from watch
    res = client.get(
        f"/api/v1/watch/{watch_uuid}",
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert tag_uuid not in res.json.get('tags', [])

    # Delete the watch
    res = client.delete(
        f"/api/v1/watch/{watch_uuid}",
        headers={'x-api-key': api_key},
    )
    assert res.status_code == 204