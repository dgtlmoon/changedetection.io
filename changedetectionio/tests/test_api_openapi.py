#!/usr/bin/env python3
"""
OpenAPI validation tests for ChangeDetection.io API

This test file specifically verifies that OpenAPI validation is working correctly
by testing various scenarios that should trigger validation errors.
"""

import time
import json
from flask import url_for
from .util import live_server_setup, wait_for_all_checks, delete_all_watches


def test_openapi_merged_spec_contains_restock_fields():
    """
    Unit test: verify that build_merged_spec_dict() correctly merges the
    restock_diff processor api.yaml into the base spec so that
    WatchBase.properties includes processor_config_restock_diff with all
    expected sub-fields.  No live server required.
    """
    from changedetectionio.api import build_merged_spec_dict

    spec = build_merged_spec_dict()
    schemas = spec['components']['schemas']

    # The merged schema for processor_config_restock_diff should exist
    assert 'processor_config_restock_diff' in schemas, \
        "processor_config_restock_diff schema missing from merged spec"

    restock_schema = schemas['processor_config_restock_diff']
    props = restock_schema.get('properties', {})

    expected_fields = {
        'in_stock_processing',
        'follow_price_changes',
        'price_change_min',
        'price_change_max',
        'price_change_threshold_percent',
    }
    missing = expected_fields - set(props.keys())
    assert not missing, f"Missing fields in processor_config_restock_diff schema: {missing}"

    # in_stock_processing must be an enum with the three valid values
    enum_values = set(props['in_stock_processing'].get('enum', []))
    assert enum_values == {'in_stock_only', 'all_changes', 'off'}, \
        f"Unexpected enum values for in_stock_processing: {enum_values}"

    # WatchBase.properties must carry a $ref to the restock schema so the
    # validation middleware can enforce it on every POST/PUT to /watch
    watchbase_props = schemas['WatchBase']['properties']
    assert 'processor_config_restock_diff' in watchbase_props, \
        "processor_config_restock_diff not wired into WatchBase.properties"
    ref = watchbase_props['processor_config_restock_diff'].get('$ref', '')
    assert 'processor_config_restock_diff' in ref, \
        f"WatchBase.processor_config_restock_diff should $ref the schema, got: {ref}"


def test_openapi_notification_format_enum_matches_code():
    """
    Unit test: the notification_format enum in api-spec.yaml must stay in step with
    valid_notification_formats, otherwise the API either rejects a format the UI offers or
    accepts one that blows up when the notification object is built.
    """
    from changedetectionio.api import build_merged_spec_dict
    from changedetectionio.notification import valid_notification_formats

    spec = build_merged_spec_dict()
    spec_enum = spec['components']['schemas']['WatchBase']['properties']['notification_format'].get('enum')

    assert spec_enum is not None, "notification_format must declare an enum in api-spec.yaml"
    assert set(spec_enum) == set(valid_notification_formats.keys()), \
        (f"api-spec.yaml notification_format enum {spec_enum} does not match "
         f"valid_notification_formats {list(valid_notification_formats.keys())}")


def test_openapi_import_rejects_invalid_enum_query_param(client, live_server, measure_memory_usage, datastore_path):
    """
    /api/v1/import takes watch config as query params - those must honour the `enum:` in the spec.
    'Text' is the classic one: it was the display name in an old release, so people still pass it,
    and a stored 'Text' makes every notification for that watch raise ValueError at send time.
    """
    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')

    res = client.post(
        url_for("import") + "?notification_format=Text",
        data='https://website1.com',
        headers={'x-api-key': api_key, 'content-type': 'text/plain'},
    )
    assert res.status_code == 400, f"Expected 400 but got {res.status_code}"
    assert b'notification_format' in res.data
    assert not live_server.app.config['DATASTORE'].data['watching'], "Nothing should have been imported"

    # Another enum field on the same code path
    res = client.post(
        url_for("import") + "?method=FETCH",
        data='https://website1.com',
        headers={'x-api-key': api_key, 'content-type': 'text/plain'},
    )
    assert res.status_code == 400, f"Expected 400 but got {res.status_code}"

    # ...and a valid value still imports and is stored
    res = client.post(
        url_for("import") + "?notification_format=htmlcolor",
        data='https://website1.com',
        headers={'x-api-key': api_key, 'content-type': 'text/plain'},
    )
    assert res.status_code == 200, f"Expected 200 but got {res.status_code}"
    watch = live_server.app.config['DATASTORE'].data['watching'][res.json[0]]
    assert watch.get('notification_format') == 'htmlcolor'

    delete_all_watches(client)


def test_openapi_validation_invalid_content_type_on_create_watch(client, live_server, measure_memory_usage, datastore_path):
    """Test that creating a watch with invalid content-type triggers OpenAPI validation error."""
    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')

    # Try to create a watch with JSON data but without proper content-type header
    res = client.post(
        url_for("createwatch"),
        data=json.dumps({"url": "https://example.com", "title": "Test Watch"}),
        headers={'x-api-key': api_key},  # Missing 'content-type': 'application/json'
        follow_redirects=True
    )

    # Should get 400 error due to OpenAPI validation failure
    assert res.status_code == 400, f"Expected 400 but got {res.status_code}"
    assert b"Validation failed" in res.data, "Should contain validation error message"
    delete_all_watches(client)


def test_openapi_validation_missing_required_field_create_watch(client, live_server, measure_memory_usage, datastore_path):
    """Test that creating a watch without required URL field triggers OpenAPI validation error."""
    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')

    # Try to create a watch without the required 'url' field
    res = client.post(
        url_for("createwatch"),
        data=json.dumps({"title": "Test Watch Without URL"}),  # Missing required 'url' field
        headers={'x-api-key': api_key, 'content-type': 'application/json'},
        follow_redirects=True
    )

    # Should get 400 error due to missing required field
    assert res.status_code == 400, f"Expected 400 but got {res.status_code}"
    assert b"Validation failed" in res.data, "Should contain validation error message"
    delete_all_watches(client)


def test_openapi_validation_invalid_field_in_request_body(client, live_server, measure_memory_usage, datastore_path):
    """Test that including invalid fields triggers OpenAPI validation error."""
    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')

    # First create a valid watch
    res = client.post(
        url_for("createwatch"),
        data=json.dumps({"url": "https://example.com", "title": "Test Watch"}),
        headers={'x-api-key': api_key, 'content-type': 'application/json'},
        follow_redirects=True
    )
    assert res.status_code == 201, "Watch creation should succeed"

    # Get the watch list to find the UUID
    res = client.get(
        url_for("createwatch"),
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    watch_uuid = list(res.json.keys())[0]

    # Now try to update the watch with an invalid field
    res = client.put(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key, 'content-type': 'application/json'},
        data=json.dumps({
            "title": "Updated title",
            "invalid_field_that_doesnt_exist": "this should cause validation error"
        }),
    )

    # Should get 400 error due to invalid field (this will be caught by internal validation)
    # Note: This tests the flow where OpenAPI validation passes but internal validation catches it
    assert res.status_code == 400, f"Expected 400 but got {res.status_code}"
    # Backend validation now returns "Unknown field(s):" message
    assert b"Unknown field" in res.data, \
            "Should contain validation error about unknown fields"
    delete_all_watches(client)


def test_openapi_validation_import_wrong_content_type(client, live_server, measure_memory_usage, datastore_path):
    """Test that import endpoint with wrong content-type triggers OpenAPI validation error."""
    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')

    # Try to import URLs with JSON content-type instead of text/plain
    res = client.post(
        url_for("import") + "?tag=test-import",
        data='https://website1.com\nhttps://website2.com',
        headers={'x-api-key': api_key, 'content-type': 'application/json'},  # Wrong content-type
        follow_redirects=True
    )

    # Should get 400 error due to content-type mismatch
    assert res.status_code == 400, f"Expected 400 but got {res.status_code}"
    assert b"Validation failed" in res.data, "Should contain validation error message"
    delete_all_watches(client)


def test_openapi_validation_import_correct_content_type_succeeds(client, live_server, measure_memory_usage, datastore_path):
    """Test that import endpoint with correct content-type succeeds (positive test)."""
    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')

    # Import URLs with correct text/plain content-type
    res = client.post(
        url_for("import") + "?tag=test-import",
        data='https://website1.com\nhttps://website2.com',
        headers={'x-api-key': api_key, 'content-type': 'text/plain'},  # Correct content-type
        follow_redirects=True
    )

    # Should succeed
    assert res.status_code == 200, f"Expected 200 but got {res.status_code}"
    assert len(res.json) == 2, "Should import 2 URLs"
    delete_all_watches(client)


def test_openapi_validation_get_requests_bypass_validation(client, live_server, measure_memory_usage, datastore_path):
    """Test that GET requests bypass OpenAPI validation entirely."""
    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')

    # Disable API token requirement first
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

    # Make GET request to list watches - should succeed even without API key or content-type
    res = client.get(url_for("createwatch"))  # No headers needed for GET
    assert res.status_code == 200, f"GET requests should succeed without OpenAPI validation, got {res.status_code}"

    # Should return JSON with watch list (empty in this case)
    assert isinstance(res.json, dict), "Should return JSON dictionary for watch list"
    delete_all_watches(client)


def test_openapi_validation_create_tag_missing_required_title(client, live_server, measure_memory_usage, datastore_path):
    """Test that creating a tag without required title triggers OpenAPI validation error."""
    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')

    # Try to create a tag without the required 'title' field
    res = client.post(
        url_for("tag"),
        data=json.dumps({"notification_urls": ["mailto:test@example.com"]}),  # Missing required 'title' field
        headers={'x-api-key': api_key, 'content-type': 'application/json'},
        follow_redirects=True
    )

    # Should get 400 error due to missing required field
    assert res.status_code == 400, f"Expected 400 but got {res.status_code}"
    assert b"Validation failed" in res.data, "Should contain validation error message"
    delete_all_watches(client)


def test_openapi_validation_watch_update_allows_partial_updates(client, live_server, measure_memory_usage, datastore_path):

    """Test that watch updates allow partial updates without requiring all fields (positive test)."""
#xxx
    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')

    # First create a valid watch
    res = client.post(
        url_for("createwatch"),
        data=json.dumps({"url": "https://example.com", "title": "Test Watch"}),
        headers={'x-api-key': api_key, 'content-type': 'application/json'},
        follow_redirects=True
    )
    assert res.status_code == 201, "Watch creation should succeed"

    # Get the watch list to find the UUID
    res = client.get(
        url_for("createwatch"),
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    watch_uuid = list(res.json.keys())[0]

    # Update only the title (partial update) - should succeed
    res = client.put(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key, 'content-type': 'application/json'},
        data=json.dumps({"title": "Updated Title Only"}),  # Only updating title, not URL
    )

    # Should succeed because UpdateWatch schema allows partial updates
    assert res.status_code == 200, f"Partial updates should succeed, got {res.status_code}"

    # Verify the update worked
    res = client.get(
        url_for("watch", uuid=watch_uuid),
        headers={'x-api-key': api_key}
    )
    assert res.status_code == 200
    assert res.json.get('title') == 'Updated Title Only', "Title should be updated"
    assert res.json.get('url') == 'https://example.com', "URL should remain unchanged"
    delete_all_watches(client)
