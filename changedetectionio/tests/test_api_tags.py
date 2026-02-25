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
    assert res.get_data(as_text=True).strip() == "{}", "Should be empty list"
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
    assert new_tag_uuid in res.get_data(as_text=True)
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

    # Test that tags are returned when listing ALL watches (issue #3854)
    res = client.get(
        url_for("createwatch"),  # GET /api/v1/watch - list all watches
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert watch_uuid in res.json, "Watch should be in the list"
    assert 'tags' in res.json[watch_uuid], "Tags field should be present in watch list"
    assert new_tag_uuid in res.json[watch_uuid]['tags'], "Tag UUID should be in tags array"

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
    assert new_tag_uuid not in res.get_data(as_text=True)

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


def test_api_tag_restock_processor_config(client, live_server, measure_memory_usage, datastore_path):
    """
    Test that a tag/group can be updated with processor_config_restock_diff via the API.
    Since Tag extends WatchBase, processor config fields injected into WatchBase are also valid for tags.
    """
    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')

    set_original_response(datastore_path=datastore_path)

    # Create a tag
    res = client.post(
        url_for("tag"),
        data=json.dumps({"title": "Restock Group"}),
        headers={'content-type': 'application/json', 'x-api-key': api_key}
    )
    assert res.status_code == 201
    tag_uuid = res.json.get('uuid')

    # Update tag with valid processor_config_restock_diff
    res = client.put(
        url_for("tag", uuid=tag_uuid),
        headers={'x-api-key': api_key, 'content-type': 'application/json'},
        data=json.dumps({
            "overrides_watch": True,
            "processor_config_restock_diff": {
                "in_stock_processing": "in_stock_only",
                "follow_price_changes": True,
                "price_change_min": 8888888
            }
        })
    )
    assert res.status_code == 200, f"PUT tag with restock config failed: {res.data}"

    # Verify the config was stored via API
    res = client.get(
        url_for("tag", uuid=tag_uuid),
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    tag_data = res.json
    assert tag_data.get('overrides_watch') == True
    assert tag_data.get('processor_config_restock_diff', {}).get('in_stock_processing') == 'in_stock_only'
    assert tag_data.get('processor_config_restock_diff', {}).get('price_change_min') == 8888888

    # Verify the value is also reflected in the UI tag edit page
    res = client.get(url_for("tags.form_tag_edit", uuid=tag_uuid))
    assert res.status_code == 200
    assert b'8888888' in res.data, "price_change_min set via API should appear in the UI tag edit form"

    # Invalid enum value should be rejected by OpenAPI spec validation
    res = client.put(
        url_for("tag", uuid=tag_uuid),
        headers={'x-api-key': api_key, 'content-type': 'application/json'},
        data=json.dumps({
            "processor_config_restock_diff": {
                "in_stock_processing": "not_a_valid_value"
            }
        })
    )
    assert res.status_code == 400
    assert b'Validation failed' in res.data

    # Clean up
    res = client.delete(
        url_for("tag", uuid=tag_uuid),
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 204


def test_roundtrip_API(client, live_server, measure_memory_usage, datastore_path):
    """
    Test the full round trip, this way we test the default Model fits back into OpenAPI spec
    :param client:
    :param live_server:
    :param measure_memory_usage:
    :param datastore_path:
    :return:
    """
    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')

    set_original_response(datastore_path=datastore_path)

    res = client.post(
        url_for("tag"),
        data=json.dumps({"title": "My tag title"}),
        headers={'content-type': 'application/json', 'x-api-key': api_key}
    )
    assert res.status_code == 201

    uuid = res.json.get('uuid')

    # Now fetch it and send it back

    res = client.get(
        url_for("tag", uuid=uuid),
        headers={'x-api-key': api_key}
    )

    tag = res.json

    # Only test with date_created (readOnly field that should be filtered out)
    # last_changed is Watch-specific and doesn't apply to Tags
    tag['date_created'] = 454444444444

    # HTTP PUT ( UPDATE an existing watch )
    res = client.put(
        url_for("tag", uuid=uuid),
        headers={'x-api-key': api_key, 'content-type': 'application/json'},
        data=json.dumps(tag),
    )
    if res.status_code != 200:
        print(f"\n=== PUT failed with {res.status_code} ===")
        print(f"Error: {res.data}")
    assert res.status_code == 200, "HTTP PUT update was sent OK"

    # Verify readOnly fields like date_created cannot be overridden
    res = client.get(
        url_for("tag", uuid=uuid),
        headers={'x-api-key': api_key}
    )
    date_created = res.json.get('date_created')
    assert date_created != 454444444444, "ReadOnly date_created should not be updateable"
    assert date_created != "454444444444", "ReadOnly date_created should not be updateable"
