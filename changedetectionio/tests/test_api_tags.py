#!/usr/bin/env python3

from flask import url_for
from .util import live_server_setup, wait_for_all_checks, set_original_response
import json
import time

def test_api_tags_listing(client, live_server, measure_memory_usage, datastore_path):
   #  live_server_setup(live_server) # Setup on conftest per function
    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')
    tag_title = 'Test Tag'


    set_original_response(datastore_path=datastore_path)


    res = client.get(
        url_for("tags"),
        headers={'x-api-key': api_key}
    )
    assert res.text.strip() == "{}", "Should be empty list"
    assert res.status_code == 200

    res = client.post(
        url_for("tag"),
        data=json.dumps({"title": tag_title}),
        headers={'content-type': 'application/json', 'x-api-key': api_key}
    )
    assert res.status_code == 201

    new_tag_uuid = res.json.get('uuid')

    # List tags - should include our new tag
    res = client.get(
        url_for("tags"),
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert new_tag_uuid in res.text
    assert res.json[new_tag_uuid]['title'] == tag_title
    assert res.json[new_tag_uuid]['notification_muted'] == False

    # Get single tag
    res = client.get(
        url_for("tag", uuid=new_tag_uuid),
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert res.json['title'] == tag_title

    # Update tag
    res = client.put(
        url_for("tag", uuid=new_tag_uuid),
        data=json.dumps({"title": "Updated Tag"}),
        headers={'content-type': 'application/json', 'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert b'OK' in res.data

    # Verify update worked
    res = client.get(
        url_for("tag", uuid=new_tag_uuid),
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert res.json['title'] == 'Updated Tag'

    # Mute tag notifications
    res = client.get(
        url_for("tag", uuid=new_tag_uuid) + "?muted=muted",
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert b'OK' in res.data

    # Verify muted status
    res = client.get(
        url_for("tag", uuid=new_tag_uuid),
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert res.json['notification_muted'] == True

    # Unmute tag
    res = client.get(
        url_for("tag", uuid=new_tag_uuid) + "?muted=unmuted",
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert b'OK' in res.data

    # Verify unmuted status
    res = client.get(
        url_for("tag", uuid=new_tag_uuid),
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert res.json['notification_muted'] == False

    # Create a watch with the tag and check it matches UUID
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("createwatch"),
        data=json.dumps({"url": test_url, "tag": "Updated Tag", "title": "Watch with tag"}),
        headers={'content-type': 'application/json', 'x-api-key': api_key},
        follow_redirects=True
    )
    assert res.status_code == 201
    watch_uuid = res.json.get('uuid')


    wait_for_all_checks()
    # Verify tag is associated with watch by name if need be
    res = client.get(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert new_tag_uuid in res.json.get('tags', [])

    # Check recheck by tag
    before_check_time = live_server.app.config['DATASTORE'].data['watching'][watch_uuid].get('last_checked')
    time.sleep(1)
    res = client.get(
       url_for("tag", uuid=new_tag_uuid) + "?recheck=true",
       headers={'x-api-key': api_key}
    )

    assert res.status_code == 200
    assert b'OK, queued 1 watches for rechecking' in res.data


    wait_for_all_checks()
    after_check_time = live_server.app.config['DATASTORE'].data['watching'][watch_uuid].get('last_checked')

    assert before_check_time != after_check_time

    # Delete tag
    res = client.delete(
        url_for("tag", uuid=new_tag_uuid),
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 204

    # Verify tag is gone
    res = client.get(
        url_for("tags"),
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert new_tag_uuid not in res.text

    # Verify tag was removed from watch
    res = client.get(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert new_tag_uuid not in res.json.get('tags', [])

    # Delete the watch
    res = client.delete(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key},
    )
    assert res.status_code == 204



