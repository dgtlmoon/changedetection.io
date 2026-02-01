#!/usr/bin/env python3

import time
from flask import url_for
from .util import live_server_setup, wait_for_all_checks, delete_all_watches
import os

import json
import uuid


def set_original_response(datastore_path):
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

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)
    return None


def set_modified_response(datastore_path):
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

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)

    return None

def is_valid_uuid(val):
    try:
        uuid.UUID(str(val))
        return True
    except ValueError:
        return False


# def test_setup(client, live_server, measure_memory_usage, datastore_path):
   #  live_server_setup(live_server) # Setup on conftest per function


def test_api_simple(client, live_server, measure_memory_usage, datastore_path):


    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')

    # Create a watch
    set_original_response(datastore_path=datastore_path)

    # Validate bad URL
    test_url = url_for('test_endpoint', _external=True )
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
    time.sleep(2)
    wait_for_all_checks(client)
    set_modified_response(datastore_path=datastore_path)
    # Trigger recheck of all ?recheck_all=1
    res = client.get(
        url_for("createwatch", recheck_all='1'),
        headers={'x-api-key': api_key},
    )
    wait_for_all_checks(client)

    time.sleep(2)
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
    watch_history = res.json
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


    # Fetch the difference between two versions (default text format)
    res = client.get(
        url_for("watchhistorydiff", uuid=watch_uuid, from_timestamp='previous', to_timestamp='latest'),
        headers={'x-api-key': api_key},
    )
    assert b'(changed) Which is across' in res.data

    # Test htmlcolor format
    res = client.get(
        url_for("watchhistorydiff", uuid=watch_uuid, from_timestamp='previous', to_timestamp='latest')+'?format=htmlcolor',
        headers={'x-api-key': api_key},
    )
    assert b'aria-label="Changed text" title="Changed text">Which is across multiple lines' in res.data

    # Test html format
    res = client.get(
        url_for("watchhistorydiff", uuid=watch_uuid, from_timestamp='previous', to_timestamp='latest')+'?format=html',
        headers={'x-api-key': api_key},
    )
    assert res.status_code == 200
    assert b'<br>' in res.data

    # Test markdown format
    res = client.get(
        url_for("watchhistorydiff", uuid=watch_uuid, from_timestamp='previous', to_timestamp='latest')+'?format=markdown',
        headers={'x-api-key': api_key},
    )
    assert res.status_code == 200

    # Test new diff preference parameters
    # Test removed=false (should hide removed content)
    res = client.get(
        url_for("watchhistorydiff", uuid=watch_uuid, from_timestamp='previous', to_timestamp='latest')+'?removed=false',
        headers={'x-api-key': api_key},
    )
    # Should not contain removed content indicator
    assert b'(removed)' not in res.data
    # Should still contain added content
    assert b'(added)' in res.data or b'which has this one new line' in res.data

    # Test added=false (should hide added content)
    # Note: The test data has replacements, not pure additions, so we test differently
    res = client.get(
        url_for("watchhistorydiff", uuid=watch_uuid, from_timestamp='previous', to_timestamp='latest')+'?added=false&replaced=false',
        headers={'x-api-key': api_key},
    )
    # With both added and replaced disabled, should have minimal content
    # Should not contain added indicators
    assert b'(added)' not in res.data

    # Test replaced=false (should hide replaced/changed content)
    res = client.get(
        url_for("watchhistorydiff", uuid=watch_uuid, from_timestamp='previous', to_timestamp='latest')+'?replaced=false',
        headers={'x-api-key': api_key},
    )
    # Should not contain changed content indicator
    assert b'(changed)' not in res.data

    # Test type=diffWords for word-level diff
    res = client.get(
        url_for("watchhistorydiff", uuid=watch_uuid, from_timestamp='previous', to_timestamp='latest')+'?type=diffWords&format=htmlcolor',
        headers={'x-api-key': api_key},
    )
    # Should contain HTML formatted diff
    assert res.status_code == 200
    assert len(res.data) > 0

    # Test combined parameters: show only additions with word diff
    res = client.get(
        url_for("watchhistorydiff", uuid=watch_uuid, from_timestamp='previous', to_timestamp='latest')+'?removed=false&replaced=false&type=diffWords',
        headers={'x-api-key': api_key},
    )
    assert res.status_code == 200
    # Should not contain removed or changed markers
    assert b'(removed)' not in res.data
    assert b'(changed)' not in res.data


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
    client.get(url_for("ui.ui_diff.diff_history_page", uuid=watch_uuid), follow_redirects=True)

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

def test_access_denied(client, live_server, measure_memory_usage, datastore_path):
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
        url_for("settings.settings_page"),
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
    delete_all_watches(client)

    res = client.post(
        url_for("settings.settings_page"),
        data={
            "requests-time_between_check-minutes": 180,
            "application-fetch_backend": "html_requests",
            "application-api_access_token_enabled": "y"
        },
        follow_redirects=True
    )
    assert b"Settings updated." in res.data

def test_api_watch_PUT_update(client, live_server, measure_memory_usage, datastore_path):

    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')
    # Create a watch
    set_original_response(datastore_path=datastore_path)
    test_url = url_for('test_endpoint', _external=True)

    # Create new
    res = client.post(
        url_for("createwatch"),
        data=json.dumps({"url": test_url,
                         'tag': "One, Two",
                         "title": "My test URL",
                         'headers': {'cookie': 'yum'},
                         "conditions": [
                             {
                                 "field": "page_filtered_text",
                                 "operator": "contains_regex",
                                 "value": "."  # contains anything
                             }
                         ],
                         "conditions_match_logic": "ALL",
                         }
                        ),
        headers={'content-type': 'application/json', 'x-api-key': api_key},
        follow_redirects=True
    )

    assert res.status_code == 201

    wait_for_all_checks(client)
    # Get a listing, it will be the first one
    res = client.get(
        url_for("createwatch"),
        headers={'x-api-key': api_key}
    )

    watch_uuid = list(res.json.keys())[0]
    assert not res.json[watch_uuid].get('viewed'), 'A newly created watch can only be unviewed'

    # Check in the edit page just to be sure
    res = client.get(
        url_for("ui.ui_edit.edit_page", uuid=watch_uuid),
    )
    assert b"cookie: yum" in res.data, "'cookie: yum' found in 'headers' section"
    assert b"One" in res.data, "Tag 'One' was found"
    assert b"Two" in res.data, "Tag 'Two' was found"

    # HTTP PUT ( UPDATE an existing watch )
    res = client.put(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key, 'content-type': 'application/json'},
        data=json.dumps({
            "title": "new title",
            'time_between_check': {'minutes': 552},
            'headers': {'cookie': 'all eaten'},
            'last_viewed': int(time.time())
        }),
    )
    assert res.status_code == 200, "HTTP PUT update was sent OK"

    # HTTP GET single watch, title should be updated
    res = client.get(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key}
    )
    assert res.json.get('title') == 'new title'
    assert res.json.get('viewed'), 'With the timestamp greater than "changed" a watch can be updated to viewed'

    # Check in the edit page just to be sure
    res = client.get(
        url_for("ui.ui_edit.edit_page", uuid=watch_uuid),
    )
    assert b"new title" in res.data, "new title found in edit page"
    assert b"552" in res.data, "552 minutes found in edit page"
    assert b"One" in res.data, "Tag 'One' was found"
    assert b"Two" in res.data, "Tag 'Two' was found"
    assert b"cookie: all eaten" in res.data, "'cookie: all eaten' found in 'headers' section"

    ######################################################

    # HTTP PUT try a field that doesn't exist

    # HTTP PUT an update
    res = client.put(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key, 'content-type': 'application/json'},
        data=json.dumps({"title": "new title", "some other field": "uh oh"}),
    )

    assert res.status_code == 400, "Should get error 400 when we give a field that doesnt exist"
    # Message will come from `flask_expects_json`
    assert b'Additional properties are not allowed' in res.data


    # Try a XSS URL
    res = client.put(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key, 'content-type': 'application/json'},
        data=json.dumps({
            'url': 'javascript:alert(document.domain)'
        }),
    )
    assert res.status_code == 400

    # Cleanup everything
    delete_all_watches(client)


def test_api_import(client, live_server, measure_memory_usage, datastore_path):

    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')

    res = client.post(
        url_for("import") + "?tag=import-test",
        data='https://website1.com\r\nhttps://website2.com',
        # We removed  'content-type': 'text/plain', the Import API should assume this if none is set #3547 #3542
        headers={'x-api-key': api_key},
        follow_redirects=True
    )

    assert res.status_code == 200
    assert len(res.json) == 2
    res = client.get(url_for("watchlist.index"))
    assert b"https://website1.com" in res.data
    assert b"https://website2.com" in res.data

    # Should see the new tag in the tag/groups list
    res = client.get(url_for('tags.tags_overview_page'))
    assert b'import-test' in res.data

def test_api_conflict_UI_password(client, live_server, measure_memory_usage, datastore_path):


    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')

    # Enable password check and diff page access bypass
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-password": "foobar", # password is now set! API should still work!
              "application-api_access_token_enabled": "y",
              "requests-time_between_check-minutes": 180,
              'application-fetch_backend': "html_requests"},
        follow_redirects=True
    )

    assert b"Password protection enabled." in res.data

    # Create a watch
    set_original_response(datastore_path=datastore_path)
    test_url = url_for('test_endpoint', _external=True)

    # Create new
    res = client.post(
        url_for("createwatch"),
        data=json.dumps({"url": test_url, "title": "My test URL" }),
        headers={'content-type': 'application/json', 'x-api-key': api_key},
        follow_redirects=True
    )

    assert res.status_code == 201


    wait_for_all_checks(client)
    url = url_for("createwatch")
    # Get a listing, it will be the first one
    res = client.get(
        url,
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200

    assert len(res.json)


def test_api_url_validation(client, live_server, measure_memory_usage, datastore_path):
    """
    Test URL validation for edge cases in both CREATE and UPDATE endpoints.
    Addresses security issues where empty/null/invalid URLs could bypass validation.

    This test ensures that:
    - CREATE endpoint rejects null, empty, and invalid URLs
    - UPDATE endpoint rejects attempts to change URL to null, empty, or invalid
    - UPDATE endpoint allows updating other fields without touching URL
    - URL validation properly checks protocol, format, and safety
    """

    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')
    set_original_response(datastore_path=datastore_path)
    test_url = url_for('test_endpoint', _external=True)

    # Test 1: CREATE with null URL should fail
    res = client.post(
        url_for("createwatch"),
        data=json.dumps({"url": None}),
        headers={'content-type': 'application/json', 'x-api-key': api_key},
        follow_redirects=True
    )
    assert res.status_code == 400, "Creating watch with null URL should fail"

    # Test 2: CREATE with empty string URL should fail
    res = client.post(
        url_for("createwatch"),
        data=json.dumps({"url": ""}),
        headers={'content-type': 'application/json', 'x-api-key': api_key},
        follow_redirects=True
    )
    assert res.status_code == 400, "Creating watch with empty string URL should fail"
    assert b'Invalid or unsupported URL' in res.data or b'required' in res.data.lower()

    # Test 3: CREATE with whitespace-only URL should fail
    res = client.post(
        url_for("createwatch"),
        data=json.dumps({"url": "   "}),
        headers={'content-type': 'application/json', 'x-api-key': api_key},
        follow_redirects=True
    )
    assert res.status_code == 400, "Creating watch with whitespace-only URL should fail"

    # Test 4: CREATE with invalid protocol should fail
    res = client.post(
        url_for("createwatch"),
        data=json.dumps({"url": "javascript:alert(1)"}),
        headers={'content-type': 'application/json', 'x-api-key': api_key},
        follow_redirects=True
    )
    assert res.status_code == 400, "Creating watch with javascript: protocol should fail"

    # Test 5: CREATE with missing protocol should fail
    res = client.post(
        url_for("createwatch"),
        data=json.dumps({"url": "example.com"}),
        headers={'content-type': 'application/json', 'x-api-key': api_key},
        follow_redirects=True
    )
    assert res.status_code == 400, "Creating watch without protocol should fail"

    # Test 6: CREATE with valid URL should succeed (baseline)
    res = client.post(
        url_for("createwatch"),
        data=json.dumps({"url": test_url, "title": "Valid URL test"}),
        headers={'content-type': 'application/json', 'x-api-key': api_key},
        follow_redirects=True
    )
    assert res.status_code == 201, "Creating watch with valid URL should succeed"
    assert is_valid_uuid(res.json.get('uuid'))
    watch_uuid = res.json.get('uuid')
    wait_for_all_checks(client)

    # Test 7: UPDATE to null URL should fail
    res = client.put(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key, 'content-type': 'application/json'},
        data=json.dumps({"url": None}),
    )
    assert res.status_code == 400, "Updating watch URL to null should fail"
    # Accept either OpenAPI validation error or our custom validation error
    assert b'URL cannot be null' in res.data or b'OpenAPI validation failed' in res.data or b'validation error' in res.data.lower()

    # Test 8: UPDATE to empty string URL should fail
    res = client.put(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key, 'content-type': 'application/json'},
        data=json.dumps({"url": ""}),
    )
    assert res.status_code == 400, "Updating watch URL to empty string should fail"
    # Accept either our custom validation error or OpenAPI/schema validation error
    assert b'URL cannot be empty' in res.data or b'OpenAPI validation' in res.data or b'Invalid or unsupported URL' in res.data

    # Test 9: UPDATE to whitespace-only URL should fail
    res = client.put(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key, 'content-type': 'application/json'},
        data=json.dumps({"url": "   \t\n  "}),
    )
    assert res.status_code == 400, "Updating watch URL to whitespace should fail"
    # Accept either our custom validation error or generic validation error
    assert b'URL cannot be empty' in res.data or b'Invalid or unsupported URL' in res.data or b'validation' in res.data.lower()

    # Test 10: UPDATE to invalid protocol should fail (javascript:)
    res = client.put(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key, 'content-type': 'application/json'},
        data=json.dumps({"url": "javascript:alert(document.domain)"}),
    )
    assert res.status_code == 400, "Updating watch URL to XSS attempt should fail"
    assert b'Invalid or unsupported URL' in res.data or b'protocol' in res.data.lower()

    # Test 11: UPDATE to file:// protocol should fail (unless ALLOW_FILE_URI is set)
    res = client.put(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key, 'content-type': 'application/json'},
        data=json.dumps({"url": "file:///etc/passwd"}),
    )
    assert res.status_code == 400, "Updating watch URL to file:// should fail by default"

    # Test 12: UPDATE other fields without URL should succeed
    res = client.put(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key, 'content-type': 'application/json'},
        data=json.dumps({"title": "Updated title without URL change"}),
    )
    assert res.status_code == 200, "Updating other fields without URL should succeed"

    # Test 13: Verify URL is still valid after non-URL update
    res = client.get(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key}
    )
    assert res.json.get('url') == test_url, "URL should remain unchanged"
    assert res.json.get('title') == "Updated title without URL change"

    # Test 14: UPDATE to valid different URL should succeed
    new_valid_url = test_url + "?new=param"
    res = client.put(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key, 'content-type': 'application/json'},
        data=json.dumps({"url": new_valid_url}),
    )
    assert res.status_code == 200, "Updating to valid different URL should succeed"

    # Test 15: Verify URL was actually updated
    res = client.get(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key}
    )
    assert res.json.get('url') == new_valid_url, "URL should be updated to new valid URL"

    # Test 16: CREATE with XSS in URL parameters should fail
    res = client.post(
        url_for("createwatch"),
        data=json.dumps({"url": "http://example.com?xss=<script>alert(1)</script>"}),
        headers={'content-type': 'application/json', 'x-api-key': api_key},
        follow_redirects=True
    )
    # This should fail because of suspicious characters check
    assert res.status_code == 400, "Creating watch with XSS in URL params should fail"

    # Cleanup
    client.delete(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key},
    )
    delete_all_watches(client)
