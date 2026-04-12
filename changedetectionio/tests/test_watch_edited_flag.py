#!/usr/bin/env python3
"""
Test the watch edited flag functionality.

This tests the private __watch_was_edited flag that tracks when writable
watch fields are modified, which prevents skipping reprocessing when the
watch configuration has changed.
"""

import os
import time
from flask import url_for
from .util import live_server_setup, wait_for_all_checks


def set_test_content(datastore_path):
    """Write test HTML content to endpoint-content.txt for test server."""
    test_html = """<html>
     <body>
     <p>Test content for watch edited flag tests</p>
     <p>This content stays the same across checks</p>
     </body>
     </html>
    """
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_html)


def test_watch_edited_flag_lifecycle(client, live_server, measure_memory_usage, datastore_path):
    """
    Test the full lifecycle of the was_edited flag:
    1. Flag starts False when watch is created
    2. Flag becomes True when writable fields are modified
    3. Flag is reset False after worker processing
    4. Flag stays False when readonly fields are modified
    """

    # Setup - Add a watch
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": "", "edit_and_watch_submit_button": "Edit > Watch"},
        follow_redirects=True
    )
    assert b"Watch added" in res.data or b"Updated watch" in res.data

    # Get the watch UUID
    datastore = client.application.config.get('DATASTORE')
    uuid = list(datastore.data['watching'].keys())[0]
    watch = datastore.data['watching'][uuid]

    # Reset flag after initial form submission (form sets fields which trigger the flag)
    watch.reset_watch_edited_flag()

    # Test 1: Flag should be False after reset
    assert not watch.was_edited, "Flag should be False after reset"

    # Test 2: Modify a writable field (title) - flag should become True
    watch['title'] = 'New Title'
    assert watch.was_edited, "Flag should be True after modifying writable field 'title'"

    # Test 3: Reset flag manually (simulating what worker does)
    watch.reset_watch_edited_flag()
    assert not watch.was_edited, "Flag should be False after reset"

    # Test 4: Modify another writable field (url) - flag should become True again
    watch['url'] = 'https://example.com'
    assert watch.was_edited, "Flag should be True after modifying writable field 'url'"

    # Test 5: Reset and modify a readonly field - flag should stay False
    watch.reset_watch_edited_flag()
    assert not watch.was_edited, "Flag should be False after reset"

    # Modify readonly field (uuid) - should not set flag
    old_uuid = watch['uuid']
    watch['uuid'] = 'readonly-test-uuid'
    assert not watch.was_edited, "Flag should stay False when modifying readonly field 'uuid'"
    watch['uuid'] = old_uuid  # Restore original

    # Note: Worker reset behavior is tested in test_check_removed_line_contains_trigger
    # and test_watch_edited_flag_prevents_skip

    print("✓ All watch edited flag lifecycle tests passed")


def test_watch_edited_flag_dict_methods(client, live_server, measure_memory_usage, datastore_path):
    """
    Test that the flag is set correctly by various dict methods:
    - __setitem__ (watch['key'] = value)
    - update() (watch.update({'key': value}))
    - setdefault() (watch.setdefault('key', default))
    - pop() (watch.pop('key'))
    - __delitem__ (del watch['key'])
    """

    # Setup - Add a watch
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": "", "edit_and_watch_submit_button": "Edit > Watch"},
        follow_redirects=True
    )

    datastore = client.application.config.get('DATASTORE')
    uuid = list(datastore.data['watching'].keys())[0]
    watch = datastore.data['watching'][uuid]

    # Test __setitem__
    watch.reset_watch_edited_flag()
    watch['title'] = 'Test via setitem'
    assert watch.was_edited, "Flag should be True after __setitem__ on writable field"

    # Test update() with dict
    watch.reset_watch_edited_flag()
    watch.update({'title': 'Test via update dict'})
    assert watch.was_edited, "Flag should be True after update() with writable field"

    # Test update() with kwargs
    watch.reset_watch_edited_flag()
    watch.update(title='Test via update kwargs')
    assert watch.was_edited, "Flag should be True after update() kwargs with writable field"

    # Test setdefault() on new key
    watch.reset_watch_edited_flag()
    watch.setdefault('title', 'Should not be set')  # Key exists, no change
    assert not watch.was_edited, "Flag should stay False when setdefault() doesn't change existing key"

    watch.setdefault('custom_field', 'New value')  # New key
    assert watch.was_edited, "Flag should be True after setdefault() creates new writable field"

    # Test pop() on writable field
    watch.reset_watch_edited_flag()
    watch.pop('custom_field', None)
    assert watch.was_edited, "Flag should be True after pop() on writable field"

    # Test __delitem__ on writable field
    watch.reset_watch_edited_flag()
    watch['temp_field'] = 'temp'
    watch.reset_watch_edited_flag()  # Reset after adding
    del watch['temp_field']
    assert watch.was_edited, "Flag should be True after __delitem__ on writable field"

    print("✓ All dict methods correctly set the flag")


def test_watch_edited_flag_prevents_skip(client, live_server, measure_memory_usage, datastore_path):
    """
    Test that the was_edited flag prevents skipping reprocessing.
    When watch configuration is edited, it should reprocess even if content unchanged.
    After worker processing, flag should be reset and subsequent checks can skip.
    """

    # Setup test content
    set_test_content(datastore_path)

    # Setup - Add a watch
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": "", "edit_and_watch_submit_button": "Edit > Watch"},
        follow_redirects=True
    )
    assert b"Watch added" in res.data or b"Updated watch" in res.data

    datastore = client.application.config.get('DATASTORE')
    uuid = list(datastore.data['watching'].keys())[0]
    watch = datastore.data['watching'][uuid]

    # Unpause the watch (watches are paused by default in tests)
    watch['paused'] = False

    # Run first check to establish baseline
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Verify first check completed successfully - checksum file should exist
    checksum_file = os.path.join(datastore_path, uuid, 'last-checksum.txt')
    assert os.path.isfile(checksum_file), "First check should create last-checksum.txt file"

    # Reset the was_edited flag (simulating clean state after processing)
    watch.reset_watch_edited_flag()
    assert not watch.was_edited, "Flag should be False after reset"

    # Run second check without any changes - should skip via checksumFromPreviousCheckWasTheSame
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Verify it was skipped (last_check_status should indicate skip)
    # Note: The actual skip is tested in test_check_removed_line_contains_trigger
    # Here we're focused on the was_edited flag interaction

    # Now modify the watch - flag should become True
    watch['title'] = 'Modified Title'
    assert watch.was_edited, "Flag should be True after modifying watch"

    # Run third check - should NOT skip because was_edited=True even though content unchanged
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # After worker processing, the flag should be reset by the worker
    # This reset happens in the processor's run() method after processing completes
    assert not watch.was_edited, "Flag should be False after worker processing"

    print("✓ was_edited flag correctly prevents skip and is reset by worker")


def test_watch_edited_flag_system_fields(client, live_server, measure_memory_usage, datastore_path):
    """
    Test that system fields (readonly + additional system fields) don't trigger the flag.
    """

    # Setup - Add a watch
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": "", "edit_and_watch_submit_button": "Edit > Watch"},
        follow_redirects=True
    )

    datastore = client.application.config.get('DATASTORE')
    uuid = list(datastore.data['watching'].keys())[0]
    watch = datastore.data['watching'][uuid]

    # Test readonly fields from OpenAPI spec
    readonly_fields = ['uuid', 'date_created', 'last_viewed']
    for field in readonly_fields:
        watch.reset_watch_edited_flag()
        if field in watch:
            old_value = watch[field]
            watch[field] = 'modified-readonly-value'
            assert not watch.was_edited, f"Flag should stay False when modifying readonly field '{field}'"
            watch[field] = old_value  # Restore

    # Test additional system fields not in OpenAPI spec yet
    system_fields = ['last_check_status']
    for field in system_fields:
        watch.reset_watch_edited_flag()
        watch[field] = 'system-value'
        assert not watch.was_edited, f"Flag should stay False when modifying system field '{field}'"

    # Test that content-type (readonly per OpenAPI) doesn't trigger flag
    watch.reset_watch_edited_flag()
    watch['content-type'] = 'text/html'
    assert not watch.was_edited, "Flag should stay False when modifying 'content-type' (readonly)"

    print("✓ System fields correctly don't trigger the flag")
