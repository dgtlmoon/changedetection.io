#!/usr/bin/env python3

import time
from flask import url_for
from .util import live_server_setup, extract_api_key_from_UI, wait_for_all_checks

import json
import uuid


def set_original_response():
    test_return_data = """<html>
       <body>
     Some initial text<br>
     <p>Which is across multiple lines</p>
     <br>
     So let's see what happens.  <br>
     <div id="sametext">Some text thats the same</div>
     <div id="changetext">Some text that will change</div>
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)
    return None


def set_modified_response():
    test_return_data = """<html>
       <body>
     Some initial text<br>
     <p>which has this one new line</p>
     <br>
     So let's see what happens.  <br>
     <div id="sametext">Some text thats the same</div>
     <div id="changetext">Some text that changes</div>
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)

    return None

def is_valid_uuid(val):
    try:
        uuid.UUID(str(val))
        return True
    except ValueError:
        return False


def test_setup(client, live_server, measure_memory_usage):
    live_server_setup(live_server)


def test_api_simple(client, live_server, measure_memory_usage):
#    live_server_setup(live_server)

    api_key = extract_api_key_from_UI(client)

    # Create a watch
    set_original_response()

    # Validate bad URL
    test_url = url_for('test_endpoint', _external=True,
                       headers={'x-api-key': api_key}, )
    res = client.post(
        url_for("createwatch"),
        data=json.dumps({"url": "h://xxxxxxxxxom"}),
        headers={'content-type': 'application/json', 'x-api-key': api_key},
        follow_redirects=True
    )
    assert res.status_code == 400

    # Create new
    res = client.post(
        url_for("createwatch"),
        data=json.dumps({"url": test_url, 'tag': "One, Two", "title": "My test URL"}),
        headers={'content-type': 'application/json', 'x-api-key': api_key},
        follow_redirects=True
    )

    assert is_valid_uuid(res.json.get('uuid'))
    watch_uuid = res.json.get('uuid')
    assert res.status_code == 201

    wait_for_all_checks(client)

    # Verify its in the list and that recheck worked
    res = client.get(
        url_for("createwatch", tag="OnE"),
        headers={'x-api-key': api_key}
    )
    assert watch_uuid in res.json.keys()
    before_recheck_info = res.json[watch_uuid]

    assert before_recheck_info['last_checked'] != 0

    #705 `last_changed` should be zero on the first check
    assert before_recheck_info['last_changed'] == 0
    assert before_recheck_info['title'] == 'My test URL'

    # Check the limit by tag doesnt return anything when nothing found
    res = client.get(
        url_for("createwatch", tag="Something else entirely"),
        headers={'x-api-key': api_key}
    )
    assert len(res.json) == 0

    wait_for_all_checks(client)

    set_modified_response()
    # Trigger recheck of all ?recheck_all=1
    client.get(
        url_for("createwatch", recheck_all='1'),
        headers={'x-api-key': api_key},
    )
    wait_for_all_checks(client)

    # Did the recheck fire?
    res = client.get(
        url_for("createwatch"),
        headers={'x-api-key': api_key},
    )
    after_recheck_info = res.json[watch_uuid]
    assert after_recheck_info['last_checked'] != before_recheck_info['last_checked']
    assert after_recheck_info['last_changed'] != 0

    # #2877 When run in a slow fetcher like playwright etc
    assert after_recheck_info['last_changed'] ==  after_recheck_info['last_checked']

    # Check history index list
    res = client.get(
        url_for("watchhistory", uuid=watch_uuid),
        headers={'x-api-key': api_key},
    )
    assert len(res.json) == 2, "Should have two history entries (the original and the changed)"

    # Fetch a snapshot by timestamp, check the right one was found
    res = client.get(
        url_for("watchsinglehistory", uuid=watch_uuid, timestamp=list(res.json.keys())[-1]),
        headers={'x-api-key': api_key},
    )
    assert b'which has this one new line' in res.data

    # Fetch a snapshot by 'latest'', check the right one was found
    res = client.get(
        url_for("watchsinglehistory", uuid=watch_uuid, timestamp='latest'),
        headers={'x-api-key': api_key},
    )
    assert b'which has this one new line' in res.data
    assert b'<div id' not in res.data

    # Fetch the HTML of the latest one
    res = client.get(
        url_for("watchsinglehistory", uuid=watch_uuid, timestamp='latest')+"?html=1",
        headers={'x-api-key': api_key},
    )
    assert b'which has this one new line' in res.data
    assert b'<div id' in res.data

    # Fetch the whole watch
    res = client.get(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key}
    )
    watch = res.json
    # @todo how to handle None/default global values?
    assert watch['history_n'] == 2, "Found replacement history section, which is in its own API"

    assert watch.get('viewed') == False
    # Loading the most recent snapshot should force viewed to become true
    client.get(url_for("diff_history_page", uuid="first"), follow_redirects=True)

    time.sleep(3)
    # Fetch the whole watch again, viewed should be true
    res = client.get(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key}
    )
    watch = res.json
    assert watch.get('viewed') == True

    # basic systeminfo check
    res = client.get(
        url_for("systeminfo"),
        headers={'x-api-key': api_key},
    )
    assert res.json.get('watch_count') == 1
    assert res.json.get('uptime') > 0.5

    ######################################################
    # Mute and Pause, check it worked
    res = client.get(
        url_for("watch", uuid=watch_uuid, paused='paused'),
        headers={'x-api-key': api_key}
    )
    assert b'OK' in res.data
    res = client.get(
        url_for("watch", uuid=watch_uuid,  muted='muted'),
        headers={'x-api-key': api_key}
    )
    assert b'OK' in res.data
    res = client.get(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key}
    )
    assert res.json.get('paused') == True
    assert res.json.get('notification_muted') == True

    # Now unpause, unmute
    res = client.get(
        url_for("watch", uuid=watch_uuid,  muted='unmuted'),
        headers={'x-api-key': api_key}
    )
    assert b'OK' in res.data
    res = client.get(
        url_for("watch", uuid=watch_uuid, paused='unpaused'),
        headers={'x-api-key': api_key}
    )
    assert b'OK' in res.data
    res = client.get(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key}
    )
    assert res.json.get('paused') == 0
    assert res.json.get('notification_muted') == 0
    ######################################################

    # Finally delete the watch
    res = client.delete(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key},
    )
    assert res.status_code == 204

    # Check via a relist
    res = client.get(
        url_for("createwatch"),
        headers={'x-api-key': api_key}
    )
    assert len(res.json) == 0, "Watch list should be empty"

def test_access_denied(client, live_server, measure_memory_usage):
    # `config_api_token_enabled` Should be On by default
    res = client.get(
        url_for("createwatch")
    )
    assert res.status_code == 403

    res = client.get(
        url_for("createwatch"),
        headers={'x-api-key': "something horrible"}
    )
    assert res.status_code == 403

    # Disable config_api_token_enabled and it should work
    res = client.post(
        url_for("settings_page"),
        data={
            "requests-time_between_check-minutes": 180,
            "application-fetch_backend": "html_requests",
            "application-api_access_token_enabled": ""
        },
        follow_redirects=True
    )

    assert b"Settings updated." in res.data

    res = client.get(
        url_for("createwatch")
    )
    assert res.status_code == 200

    # Cleanup everything
    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

    res = client.post(
        url_for("settings_page"),
        data={
            "requests-time_between_check-minutes": 180,
            "application-fetch_backend": "html_requests",
            "application-api_access_token_enabled": "y"
        },
        follow_redirects=True
    )
    assert b"Settings updated." in res.data

def test_api_watch_PUT_update(client, live_server, measure_memory_usage):

    #live_server_setup(live_server)
    api_key = extract_api_key_from_UI(client)

    # Create a watch
    set_original_response()
    test_url = url_for('test_endpoint', _external=True,
                       headers={'x-api-key': api_key}, )

    # Create new
    res = client.post(
        url_for("createwatch"),
        data=json.dumps({"url": test_url, 'tag': "One, Two", "title": "My test URL", 'headers': {'cookie': 'yum'} }),
        headers={'content-type': 'application/json', 'x-api-key': api_key},
        follow_redirects=True
    )

    assert res.status_code == 201


    # Get a listing, it will be the first one
    res = client.get(
        url_for("createwatch"),
        headers={'x-api-key': api_key}
    )

    watch_uuid = list(res.json.keys())[0]

    # Check in the edit page just to be sure
    res = client.get(
        url_for("edit_page", uuid=watch_uuid),
    )
    assert b"cookie: yum" in res.data, "'cookie: yum' found in 'headers' section"
    assert b"One" in res.data, "Tag 'One' was found"
    assert b"Two" in res.data, "Tag 'Two' was found"

    # HTTP PUT ( UPDATE an existing watch )
    res = client.put(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key, 'content-type': 'application/json'},
        data=json.dumps({"title": "new title", 'time_between_check': {'minutes': 552}, 'headers': {'cookie': 'all eaten'}}),
    )
    assert res.status_code == 200, "HTTP PUT update was sent OK"

    # HTTP GET single watch, title should be updated
    res = client.get(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key}
    )
    assert res.json.get('title') == 'new title'

    # Check in the edit page just to be sure
    res = client.get(
        url_for("edit_page", uuid=watch_uuid),
    )
    assert b"new title" in res.data, "new title found in edit page"
    assert b"552" in res.data, "552 minutes found in edit page"
    assert b"One" in res.data, "Tag 'One' was found"
    assert b"Two" in res.data, "Tag 'Two' was found"
    assert b"cookie: all eaten" in res.data, "'cookie: all eaten' found in 'headers' section"

    ######################################################

    # HTTP PUT try a field that doenst exist

    # HTTP PUT an update
    res = client.put(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key, 'content-type': 'application/json'},
        data=json.dumps({"title": "new title", "some other field": "uh oh"}),
    )

    assert res.status_code == 400, "Should get error 400 when we give a field that doesnt exist"
    # Message will come from `flask_expects_json`
    assert b'Additional properties are not allowed' in res.data

    # Cleanup everything
    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data


def test_api_import(client, live_server, measure_memory_usage):
    api_key = extract_api_key_from_UI(client)

    res = client.post(
        url_for("import") + "?tag=import-test",
        data='https://website1.com\r\nhttps://website2.com',
        headers={'x-api-key': api_key},
        follow_redirects=True
    )

    assert res.status_code == 200
    assert len(res.json) == 2
    res = client.get(url_for("index"))
    assert b"https://website1.com" in res.data
    assert b"https://website2.com" in res.data

    # Should see the new tag in the tag/groups list
    res = client.get(url_for('tags.tags_overview_page'))
    assert b'import-test' in res.data
    