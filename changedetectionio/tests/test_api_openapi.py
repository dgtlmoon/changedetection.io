#!/usr/bin/env python3
"""
OpenAPI validation tests for ChangeDetection.io API

This test file specifically verifies that OpenAPI validation is working correctly
by testing various scenarios that should trigger validation errors.
"""

import time
import json
from flask import url_for
from .util import live_server_setup, wait_for_all_checks


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
    assert b"OpenAPI validation failed" in res.data, "Should contain OpenAPI validation error message"


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
    assert b"OpenAPI validation failed" in res.data, "Should contain OpenAPI validation error message"


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
    # With patternProperties for processor_config_*, the error message format changed slightly
    assert (b"Additional properties are not allowed" in res.data or
            b"does not match any of the regexes" in res.data), \
            "Should contain validation error about additional/invalid properties"


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
    assert b"OpenAPI validation failed" in res.data, "Should contain OpenAPI validation error message"


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
    assert b"OpenAPI validation failed" in res.data, "Should contain OpenAPI validation error message"


def test_openapi_validation_watch_update_allows_partial_updates(client, live_server, measure_memory_usage, datastore_path):
    """Test that watch updates allow partial updates without requiring all fields (positive test)."""
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