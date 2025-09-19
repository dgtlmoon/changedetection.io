from copy import copy

from flask import url_for
import json
import time
from .util import live_server_setup, wait_for_all_checks

all_expected_watch_keys = ['body', 'browser_steps', 'browser_steps_last_error_step', 'conditions', 'conditions_match_logic', 'check_count', 'check_unique_lines', 'consecutive_filter_failures', 'content-type', 'date_created', 'extract_text', 'fetch_backend', 'fetch_time', 'filter_failure_notification_send', 'filter_text_added', 'filter_text_removed', 'filter_text_replaced', 'follow_price_changes', 'has_ldjson_price_data', 'headers', 'ignore_text', 'ignore_status_codes', 'in_stock_only', 'include_filters', 'last_checked', 'last_error', 'last_notification_error', 'last_viewed', 'method', 'notification_alert_count', 'notification_body', 'notification_format', 'notification_muted', 'notification_screenshot', 'notification_title', 'notification_urls', 'page_title', 'paused', 'previous_md5', 'previous_md5_before_filters', 'processor', 'price_change_threshold_percent', 'proxy', 'remote_server_reply', 'sort_text_alphabetically', 'subtractive_selectors', 'tag', 'tags', 'text_should_not_be_present', 'time_between_check', 'time_between_check_use_default', 'time_schedule_limit', 'title', 'track_ldjson_price_data', 'trim_text_whitespace', 'remove_duplicate_lines', 'trigger_text', 'url', 'use_page_title_in_list', 'uuid', 'webdriver_delay', 'webdriver_js_execute_code', 'last_changed', 'history_n', 'viewed', 'link']

def test_api_search(client, live_server):
   #  live_server_setup(live_server) # Setup on conftest per function
    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')

    watch_data = {}
    # Add some test watches
    urls = [
        'https://example.com/page1',
        'https://example.org/testing',
        'https://test-site.com/example'
    ]

    # Import the test URLs
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": "\r\n".join(urls)},
        follow_redirects=True
    )
    assert b"3 Imported" in res.data
    wait_for_all_checks(client)

    # Get a listing, it will be the first one
    watches_response = client.get(
        url_for("createwatch"),
        headers={'x-api-key': api_key}
    )

    # Add a title to one watch for title search testing
    for uuid, watch in watches_response.json.items():
        if urls[0] == watch['url']:
            # HTTP PUT ( UPDATE an existing watch )
            client.put(
                url_for("watch", uuid=uuid),
                headers={'x-api-key': api_key, 'content-type': 'application/json'},
                data=json.dumps({'title': 'Example Title Test'}),
            )
        missing_keys = all_expected_watch_keys - watch.keys()
        assert not missing_keys, 'A single item in the result of a list watches api call must be a full watch model'

    # Test search by URL
    res = client.get(url_for("search")+"?q=https://example.com/page1", headers={'x-api-key': api_key, 'content-type': 'application/json'})
    assert len(res.json) == 1
    first_search_resp_as_dict = list(res.json.values())[0]
    assert first_search_resp_as_dict['url'] == urls[0]
    missing_keys = all_expected_watch_keys - first_search_resp_as_dict.keys()
    assert not missing_keys, 'A single item in the result of a search watches api call must be a full watch model'

    # Test search by URL - partial should NOT match without ?partial=true flag
    res = client.get(url_for("search")+"?q=https://example", headers={'x-api-key': api_key, 'content-type': 'application/json'})
    assert len(res.json) == 0


    # Test search by title
    res = client.get(url_for("search")+"?q=Example Title Test", headers={'x-api-key': api_key, 'content-type': 'application/json'})
    assert len(res.json) == 1
    assert list(res.json.values())[0]['url'] == urls[0]
    assert list(res.json.values())[0]['title'] == 'Example Title Test'

    # Test search that should return multiple results (partial = true)
    res = client.get(url_for("search")+"?q=https://example&partial=true", headers={'x-api-key': api_key, 'content-type': 'application/json'})
    assert len(res.json) == 2

    # Test empty search
    res = client.get(url_for("search")+"?q=", headers={'x-api-key': api_key, 'content-type': 'application/json'})
    assert res.status_code == 400

    # Add a tag to test search with tag filter
    tag_name = 'test-tag'
    res = client.post(
        url_for("tag"),
        data=json.dumps({"title": tag_name}),
        headers={'content-type': 'application/json', 'x-api-key': api_key}
    )
    assert res.status_code == 201
    tag_uuid = res.json['uuid']

    # Add the tag to one watch
    for uuid, watch in watches_response.json.items():
        if urls[2] == watch['url']:
            client.put(
                url_for("watch", uuid=uuid),
                headers={'x-api-key': api_key, 'content-type': 'application/json'},
                data=json.dumps({'tags': [tag_uuid]}),
            )


    # Test search with tag filter and q
    res = client.get(url_for("search") + f"?q={urls[2]}&tag={tag_name}", headers={'x-api-key': api_key, 'content-type': 'application/json'})
    assert len(res.json) == 1
    assert list(res.json.values())[0]['url'] == urls[2]

