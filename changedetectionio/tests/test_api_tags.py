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


def test_api_tags_extended_properties(client, live_server, measure_memory_usage, datastore_path):
    """Test restock-specific tag properties including restock_settings and overrides_watch."""
    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')
    
    # Test creating a tag with extended properties
    extended_tag_data = {
        "title": "Extended Test Tag",
        "overrides_watch": True,
        "restock_settings": {
            "in_stock_processing": "in_stock_only",
            "follow_price_changes": True,
            "price_change_min": 10.50,
            "price_change_max": 100.00,
            "price_change_threshold_percent": 5.0
        }
    }
    
    res = client.post(
        url_for("tag"),
        data=json.dumps(extended_tag_data),
        headers={'content-type': 'application/json', 'x-api-key': api_key}
    )
    assert res.status_code == 201
    new_tag_uuid = res.json.get('uuid')
    
    # Verify all properties were set correctly
    res = client.get(
        url_for("tag", uuid=new_tag_uuid),
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    tag_data = res.json
    
    assert tag_data['title'] == "Extended Test Tag"
    assert tag_data['overrides_watch'] == True
    
    # Check restock_settings
    restock = tag_data['restock_settings']
    assert restock['in_stock_processing'] == "in_stock_only"
    assert restock['follow_price_changes'] == True
    assert restock['price_change_min'] == 10.50
    assert restock['price_change_max'] == 100.00
    assert restock['price_change_threshold_percent'] == 5.0
    
    # Test updating individual properties
    update_data = {
        "restock_settings": {
            "in_stock_processing": "all_changes",
            "follow_price_changes": False,
            "price_change_min": 5.00,
            "price_change_max": None,  # Test null value
            "price_change_threshold_percent": 10.0
        },
        "overrides_watch": False
    }
    
    res = client.post(
        url_for("tag", uuid=new_tag_uuid),
        data=json.dumps(update_data),
        headers={'content-type': 'application/json', 'x-api-key': api_key}
    )
    assert res.status_code == 200
    
    # Verify updates
    res = client.get(
        url_for("tag", uuid=new_tag_uuid),
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    updated_data = res.json
    
    assert updated_data['restock_settings']['in_stock_processing'] == "all_changes"
    assert updated_data['restock_settings']['follow_price_changes'] == False
    assert updated_data['restock_settings']['price_change_min'] == 5.00
    assert updated_data['restock_settings']['price_change_max'] is None
    assert updated_data['restock_settings']['price_change_threshold_percent'] == 10.0
    assert updated_data['overrides_watch'] == False
    
    # Test validation errors
    # Invalid in_stock_processing
    invalid_data = {"restock_settings": {"in_stock_processing": "invalid_mode"}}
    res = client.post(
        url_for("tag", uuid=new_tag_uuid),
        data=json.dumps(invalid_data),
        headers={'content-type': 'application/json', 'x-api-key': api_key}
    )
    assert res.status_code == 400
    assert b"Invalid in_stock_processing value" in res.data
    
    # Invalid price_change_threshold_percent
    invalid_data = {"restock_settings": {"price_change_threshold_percent": 150}}
    res = client.post(
        url_for("tag", uuid=new_tag_uuid),
        data=json.dumps(invalid_data),
        headers={'content-type': 'application/json', 'x-api-key': api_key}
    )
    assert res.status_code == 400
    assert b"must be between 0 and 100" in res.data
    

    
    # Test tags listing includes new properties
    res = client.get(
        url_for("tags"),
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    tags_list = res.json
    assert new_tag_uuid in tags_list
    tag_in_list = tags_list[new_tag_uuid]
    
    # Verify all properties are included in listing
    assert 'overrides_watch' in tag_in_list
    assert 'restock_settings' in tag_in_list
    
    # Clean up
    res = client.delete(
        url_for("tag", uuid=new_tag_uuid),
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 204



