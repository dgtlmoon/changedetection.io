#!/usr/bin/env python3

from flask import url_for
from .util import live_server_setup
import json

def test_api_notifications_crud(client, live_server):
   #  live_server_setup(live_server) # Setup on conftest per function
    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')

    # Confirm notifications are initially empty
    res = client.get(
        url_for("notifications"),
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert res.json == {"notification_urls": []}

    # Add notification URLs
    test_urls = ["posts://example.com/notify1", "posts://example.com/notify2"]
    res = client.post(
        url_for("notifications"),
        data=json.dumps({"notification_urls": test_urls}),
        headers={'content-type': 'application/json', 'x-api-key': api_key}
    )
    assert res.status_code == 201
    for url in test_urls:
        assert url in res.json["notification_urls"]

    # Confirm the notification URLs were added
    res = client.get(
        url_for("notifications"),
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    for url in test_urls:
        assert url in res.json["notification_urls"]

    # Delete one notification URL
    res = client.delete(
        url_for("notifications"),
        data=json.dumps({"notification_urls": [test_urls[0]]}),
        headers={'content-type': 'application/json', 'x-api-key': api_key}
    )
    assert res.status_code == 204

    # Confirm it was removed and the other remains
    res = client.get(
        url_for("notifications"),
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert test_urls[0] not in res.json["notification_urls"]
    assert test_urls[1] in res.json["notification_urls"]

    # Try deleting a non-existent URL
    res = client.delete(
        url_for("notifications"),
        data=json.dumps({"notification_urls": ["posts://nonexistent.com"]}),
        headers={'content-type': 'application/json', 'x-api-key': api_key}
    )
    assert res.status_code == 400

    res = client.post(
        url_for("notifications"),
        data=json.dumps({"notification_urls": test_urls}),
        headers={'content-type': 'application/json', 'x-api-key': api_key}
    )
    assert res.status_code == 201

    # Replace with a new list
    replacement_urls = ["posts://new.example.com"]
    res = client.put(
        url_for("notifications"),
        data=json.dumps({"notification_urls": replacement_urls}),
        headers={'content-type': 'application/json', 'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert res.json["notification_urls"] == replacement_urls

    # Replace with an empty list
    res = client.put(
        url_for("notifications"),
        data=json.dumps({"notification_urls": []}),
        headers={'content-type': 'application/json', 'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert res.json["notification_urls"] == []

    # Provide an invalid AppRise URL to trigger validation error
    invalid_urls = ["ftp://not-app-rise"]
    res = client.post(
        url_for("notifications"),
        data=json.dumps({"notification_urls": invalid_urls}),
        headers={'content-type': 'application/json', 'x-api-key': api_key}
    )
    assert res.status_code == 400
    assert "is not a valid AppRise URL." in res.data.decode()

    res = client.put(
        url_for("notifications"),
        data=json.dumps({"notification_urls": invalid_urls}),
        headers={'content-type': 'application/json', 'x-api-key': api_key}
    )
    assert res.status_code == 400
    assert "is not a valid AppRise URL." in res.data.decode()

    