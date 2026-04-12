#!/usr/bin/env python3
"""
Test that changing global settings or tag configurations forces reprocessing.

When settings or tag configurations change, all affected watches need to
reprocess even if their content hasn't changed, because configuration affects
the processing result.
"""

import os
import time
from flask import url_for
from .util import wait_for_all_checks


def test_settings_change_forces_reprocess(client, live_server, measure_memory_usage, datastore_path):
    """
    Test that changing global settings clears all checksums to force reprocessing.
    """

    # Setup test content
    test_html = """<html>
     <body>
     <p>Test content that stays the same</p>
     </body>
     </html>
    """
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_html)

    test_url = url_for('test_endpoint', _external=True)

    # Add two watches
    datastore = client.application.config.get('DATASTORE')
    uuid1 = datastore.add_watch(url=test_url, extras={'title': 'Watch 1'})
    uuid2 = datastore.add_watch(url=test_url, extras={'title': 'Watch 2'})

    # Unpause watches
    datastore.data['watching'][uuid1]['paused'] = False
    datastore.data['watching'][uuid2]['paused'] = False

    # First check - establishes baseline
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Verify checksum files were created
    checksum1 = os.path.join(datastore_path, uuid1, 'last-checksum.txt')
    checksum2 = os.path.join(datastore_path, uuid2, 'last-checksum.txt')
    assert os.path.isfile(checksum1), "First check should create checksum file for watch 1"
    assert os.path.isfile(checksum2), "First check should create checksum file for watch 2"

    # Change global settings (any setting will do)
    res = client.post(
        url_for("settings.settings_page"),
        data={
            "application-empty_pages_are_a_change": "",
            "requests-time_between_check-minutes": 180,
            'application-fetch_backend': "html_requests"
        },
        follow_redirects=True
    )
    assert b"Settings updated." in res.data

    # Give it a moment to process
    time.sleep(0.5)

    # Verify ALL checksum files were deleted
    assert not os.path.isfile(checksum1), "Settings change should delete checksum for watch 1"
    assert not os.path.isfile(checksum2), "Settings change should delete checksum for watch 2"

    # Next check should reprocess (not skip) and recreate checksums
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Verify checksum files were recreated
    assert os.path.isfile(checksum1), "Reprocessing should recreate checksum file for watch 1"
    assert os.path.isfile(checksum2), "Reprocessing should recreate checksum file for watch 2"

    print("✓ Settings change forces reprocessing of all watches")


def test_tag_change_forces_reprocess(client, live_server, measure_memory_usage, datastore_path):
    """
    Test that changing a tag configuration clears checksums only for watches with that tag.
    """

    # Setup test content
    test_html = """<html>
     <body>
     <p>Test content that stays the same</p>
     </body>
     </html>
    """
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_html)

    test_url = url_for('test_endpoint', _external=True)

    # Create a tag
    datastore = client.application.config.get('DATASTORE')
    tag_uuid = datastore.add_tag('Test Tag')

    # Add watches - one with tag, one without
    uuid_with_tag = datastore.add_watch(url=test_url, extras={'title': 'Watch With Tag', 'tags': [tag_uuid]})
    uuid_without_tag = datastore.add_watch(url=test_url, extras={'title': 'Watch Without Tag'})

    # Unpause watches
    datastore.data['watching'][uuid_with_tag]['paused'] = False
    datastore.data['watching'][uuid_without_tag]['paused'] = False

    # First check - establishes baseline
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Verify checksum files were created
    checksum_with = os.path.join(datastore_path, uuid_with_tag, 'last-checksum.txt')
    checksum_without = os.path.join(datastore_path, uuid_without_tag, 'last-checksum.txt')
    assert os.path.isfile(checksum_with), "First check should create checksum for tagged watch"
    assert os.path.isfile(checksum_without), "First check should create checksum for untagged watch"

    # Edit the tag (change notification_muted as an example)
    tag = datastore.data['settings']['application']['tags'][tag_uuid]
    res = client.post(
        url_for("tags.form_tag_edit_submit", uuid=tag_uuid),
        data={
            'title': 'Test Tag',
            'notification_muted': 'y',
            'overrides_watch': 'n'
        },
        follow_redirects=True
    )
    assert b"Updated" in res.data

    # Give it a moment to process
    time.sleep(0.5)

    # Verify ONLY the tagged watch's checksum was deleted
    assert not os.path.isfile(checksum_with), "Tag change should delete checksum for watch WITH tag"
    assert os.path.isfile(checksum_without), "Tag change should NOT delete checksum for watch WITHOUT tag"

    # Next check should reprocess tagged watch and recreate its checksum
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Verify tagged watch's checksum was recreated
    assert os.path.isfile(checksum_with), "Reprocessing should recreate checksum for tagged watch"
    assert os.path.isfile(checksum_without), "Untagged watch should still have its checksum"

    print("✓ Tag change forces reprocessing only for watches with that tag")


def test_tag_change_via_api_forces_reprocess(client, live_server, measure_memory_usage, datastore_path):
    """
    Test that updating a tag via API also clears checksums for affected watches.
    """

    # Setup test content
    test_html = """<html>
     <body>
     <p>Test content</p>
     </body>
     </html>
    """
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_html)

    test_url = url_for('test_endpoint', _external=True)

    # Create a tag
    datastore = client.application.config.get('DATASTORE')
    tag_uuid = datastore.add_tag('API Test Tag')

    # Add watch with tag
    uuid_with_tag = datastore.add_watch(url=test_url, extras={'title': 'API Watch'})
    datastore.data['watching'][uuid_with_tag]['paused'] = False
    datastore.data['watching'][uuid_with_tag]['tags'] = [tag_uuid]
    datastore.data['watching'][uuid_with_tag].commit()

    # First check
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Verify checksum exists
    checksum_file = os.path.join(datastore_path, uuid_with_tag, 'last-checksum.txt')
    assert os.path.isfile(checksum_file), "First check should create checksum file"

    # Update tag via API
    res = client.put(
        f'/api/v1/tag/{tag_uuid}',
        json={'notification_muted': True},
        headers={'x-api-key': datastore.data['settings']['application']['api_access_token']}
    )
    assert res.status_code == 200, f"API call failed with status {res.status_code}: {res.data}"

    # Give it more time for async operations
    time.sleep(1.0)

    # Debug: Check if checksum still exists
    if os.path.isfile(checksum_file):
        # Read checksum to see if it changed
        with open(checksum_file, 'r') as f:
            checksum_content = f.read()
            print(f"Checksum still exists: {checksum_content}")

    # Verify checksum was deleted
    assert not os.path.isfile(checksum_file), "API tag update should delete checksum"

    print("✓ Tag update via API forces reprocessing")
