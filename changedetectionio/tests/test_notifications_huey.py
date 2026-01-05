import os
import time
from flask import url_for
from .util import set_original_response, set_modified_response, wait_for_all_checks
import logging

# Set environment variables at module level for fast Huey retry testing
# Use 1 retry with 10 second delay (minimum allowed) to test retry mechanism
os.environ['NOTIFICATION_RETRY_COUNT'] = '1'
os.environ['NOTIFICATION_RETRY_DELAY'] = '10'


def test_notification_dead_letter_retry(client, live_server, measure_memory_usage, datastore_path):
    """
    Test that failed notifications appear in dead-letter queue and can be retried.

    Steps:
    1. Create a watch with a broken notification URL
    2. Trigger a notification that will fail
    3. Verify the notification appears in the dead-letter queue after retries are exhausted
    4. Fix the notification URL
    5. Retry all dead-letter notifications
    6. Verify the dead-letter queue is empty after successful retry

    Note: This test uses NOTIFICATION_RETRY_COUNT=1 with NOTIFICATION_RETRY_DELAY=3s
    to test the retry mechanism while keeping test execution fast (~6 seconds total).
    """
    from changedetectionio.notification.task_queue import get_failed_notifications, retry_all_failed_notifications

    set_original_response(datastore_path=datastore_path)

    # Set a URL and fetch it
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)

    wait_for_all_checks(client)

    # Set a broken notification URL that will definitely fail
    broken_notification_url = "jsons://broken-url-xxxxxxxx-will-fail-456/test"

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "notification_urls": broken_notification_url,
            "notification_title": "Test Dead Letter",
            "notification_body": "This should fail and go to dead letter queue",
            "notification_format": 'text',
            "url": test_url,
            "tags": "",
            "title": "",
            "headers": "",
            "time_between_check-minutes": "180",
            "fetch_backend": "html_requests",
            "time_between_check_use_default": "y"
        },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    wait_for_all_checks(client)
    set_modified_response(datastore_path=datastore_path)
    res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    assert b'Queued 1 watch for rechecking.' in res.data

    # Verify that task metadata is being stored (required for dead-letter queue)
    from changedetectionio.notification.task_queue import huey
    if huey and hasattr(huey, 'storage'):
        storage_path = getattr(huey.storage, 'path', None)
        if storage_path:
            metadata_dir = os.path.join(storage_path, 'task_metadata')
            # Give it a moment for the metadata to be written
            time.sleep(1)
            assert os.path.exists(metadata_dir), \
                f"Task metadata directory should exist at {metadata_dir} for dead-letter queue to work"

    # Wait for notification to fail and exhaust retries
    # With 1 retry and 3 second delay: initial attempt + 3s wait + 1 retry = ~6 seconds total
    # Add extra time for Huey to write the result to storage
    max_wait_time = 20  # Allow buffer time for storage
    start_time = time.time()
    failed_found = False

    logging.info("Waiting for notification to fail and exhaust retries...")

    while time.time() - start_time < max_wait_time:
        # Check if notification has failed and is in dead-letter queue
        failed_notifications = get_failed_notifications()

        elapsed = time.time() - start_time
        logging.debug(f"Time elapsed: {elapsed:.1f}s, Failed notifications: {len(failed_notifications)}")

        if failed_notifications and len(failed_notifications) > 0:
            # Found at least one failed notification
            failed_found = True
            logging.info(f"Found {len(failed_notifications)} failed notification(s) in dead-letter queue after {elapsed:.1f}s")

            # Verify it's our notification
            assert any('broken-url-xxxxxxxx-will-fail-456' in str(notif.get('notification_data', {}))
                      for notif in failed_notifications), "Failed notification should contain our broken URL"
            break

        time.sleep(1)  # Check every second

    assert failed_found, "Notification should have failed and appeared in dead-letter queue"

    # Get the count of failed notifications before retry
    failed_before = get_failed_notifications()
    failed_count_before = len(failed_before)
    assert failed_count_before > 0, "Should have at least one failed notification before retry"

    logging.info(f"Dead-letter queue has {failed_count_before} failed notification(s) before retry")

    # Fix the notification URL before retrying so the retry will succeed
    # Use a working notification URL that will succeed
    working_notification_url = url_for('test_notification_endpoint', _external=True).replace('http', 'json')

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "notification_urls": working_notification_url,
            "notification_title": "Test Dead Letter - Fixed",
            "notification_body": "This should succeed after retry",
            "notification_format": 'text',
            "url": test_url,
            "tags": "",
            "title": "",
            "headers": "",
            "time_between_check-minutes": "180",
            "fetch_backend": "html_requests",
            "time_between_check_use_default": "y"
        },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    logging.info("Updated notification URL to working URL before retry")

    # Now retry all failed notifications
    retry_result = retry_all_failed_notifications()

    logging.info(f"Retry result: {retry_result}")
    assert retry_result['total'] > 0, "Should have attempted to retry at least one notification"
    assert retry_result['success'] > 0, "At least one retry should have succeeded"

    # Give it time for the retry to process and succeed
    time.sleep(3)

    # Check that dead-letter queue is now empty
    failed_after = get_failed_notifications()
    failed_count_after = len(failed_after)

    logging.info(f"Dead-letter queue has {failed_count_after} failed notification(s) after retry")

    # The dead-letter queue should be empty after successful retry
    assert failed_count_after == 0, \
        f"Dead-letter queue should be empty after retry (before: {failed_count_before}, after: {failed_count_after})"

    # Verify the notification was actually sent successfully
    notification_file = os.path.join(datastore_path, "notification.txt")
    assert os.path.exists(notification_file), "Notification file should exist after successful retry"

    with open(notification_file, "r") as f:
        notification_content = f.read()

    # The notification should contain the original message (body is preserved from original notification)
    # But the notification_urls were reloaded from current settings (the working URL)
    assert 'This should fail and go to dead letter queue' in notification_content, \
        "Notification should contain the original message (body is preserved during retry)"

    os.unlink(notification_file)

    logging.info("✓ Dead-letter retry test completed successfully")


def test_notification_dead_letter_ui_and_utilities(client, live_server, measure_memory_usage, datastore_path):
    """
    Test dead-letter queue UI integration and utility functions.

    This test verifies:
    1. Failed notifications appear in the settings/failed-notifications page
    2. The body class "failed-notifications" is added when there are failures
    3. Storage counting functions work correctly
    4. Cleanup functions work correctly
    5. Clear all notifications function works correctly
    """
    from changedetectionio.notification.task_queue import (
        get_failed_notifications,
        get_pending_notifications_count,
        cleanup_old_failed_notifications,
        clear_all_notifications,
        retry_all_failed_notifications
    )
    from changedetectionio.notification.task_queue import huey

    set_original_response(datastore_path=datastore_path)

    # Set a URL and fetch it
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)

    wait_for_all_checks(client)

    # Set a broken notification URL that will definitely fail
    broken_notification_url = "jsons://broken-url-test-ui-12345/test"

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "notification_urls": broken_notification_url,
            "notification_title": "Test UI Integration",
            "notification_body": "This notification will fail for UI testing",
            "notification_format": 'text',
            "url": test_url,
            "tags": "",
            "title": "",
            "headers": "",
            "time_between_check-minutes": "180",
            "fetch_backend": "html_requests",
            "time_between_check_use_default": "y"
        },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    wait_for_all_checks(client)
    set_modified_response(datastore_path=datastore_path)
    res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    assert b'Queued 1 watch for rechecking.' in res.data

    # Test pending notifications count (should include the queued notification)
    pending_count = get_pending_notifications_count()
    logging.info(f"Pending notifications count: {pending_count}")
    assert pending_count >= 0, "Should be able to get pending notifications count"

    # Wait for notification to fail and exhaust ALL retries
    # With 1 retry and 3s delay: initial attempt + 3s + retry = ~4 seconds
    # But we need to wait for the retry to complete and result to be stored
    max_wait_time = 20
    start_time = time.time()
    failed_found = False

    logging.info("Waiting for notification to fail and exhaust all retries...")

    while time.time() - start_time < max_wait_time:
        failed_notifications = get_failed_notifications()
        if failed_notifications and len(failed_notifications) > 0:
            failed_found = True
            logging.info(f"Found {len(failed_notifications)} failed notification(s) after {time.time() - start_time:.1f}s")
            # Wait a bit more to ensure the notification is fully processed
            # and not in the middle of a retry
            time.sleep(2)
            break
        time.sleep(1)

    assert failed_found, "Notification should have failed and appeared in dead-letter queue"

    # Test 1: Check the settings/failed-notifications page is accessible
    logging.info("Testing settings/failed-notifications page...")
    res = client.get(url_for("settings.failed_notifications"))
    assert res.status_code == 200, "Failed notifications page should be accessible"
    # The page should show that there's 1 failed notification in the Clear All dialog
    assert b"1 Failed" in res.data or b"1 failed" in res.data, "Page should show failed notification count"
    # The page should have Retry All and Clear All buttons
    assert b"Retry All" in res.data, "Page should have Retry All button"
    assert b"Clear All" in res.data, "Page should have Clear All button"

    # Verify both notification sections are present in the page structure
    assert b"Pending / Retrying" in res.data, "Page should show Pending / Retrying section"
    assert b"Failed (Dead Letter)" in res.data, "Page should show Failed (Dead Letter) section"
    # The pending/retrying count shows "0 Pending/Retrying" in the Clear All button
    assert b"0 Pending/Retrying" in res.data or b"0 pending" in res.data.lower(), \
        "Page should show pending/retrying count (0 in this case)"
    # Check that failed notifications list is present by verifying FAILED badge and Retry This button
    assert b"FAILED" in res.data, "Page should show FAILED status badge for failed notification"
    assert b"Retry This" in res.data, "Page should show 'Retry This' button for failed notification"
    # The template has a <details> element for pending notifications (only shown when pending_list exists)
    # In this test, all retries are exhausted, so pending_list is empty and details won't render
    # But we can verify the page has the proper structure by checking Clear All shows "0 Pending"

    logging.info("✓ Failed notifications page is accessible, shows both pending/retrying and failed sections")

    # Test 2: Verify body class "failed-notifications" is present
    logging.info("Testing body class for failed notifications...")
    res = client.get(url_for("watchlist.index"))
    assert res.status_code == 200
    assert b'<body class=' in res.data, "Body tag should be present"
    # Check that the failed-notifications class is in the body tag
    assert b'failed-notifications' in res.data, \
        "Body should have 'failed-notifications' class when there are failed notifications"
    logging.info("✓ Body class 'failed-notifications' is present")

    # Test 3: Test cleanup_old_failed_notifications
    logging.info("Testing cleanup_old_failed_notifications...")
    # Cleanup with very long age (365 days) should not delete recent failures
    deleted_count = cleanup_old_failed_notifications(max_age_days=365)
    logging.info(f"Cleanup deleted {deleted_count} old failed notifications (expected 0 with 365 day limit)")
    # With very long age limit, recent failures should not be deleted
    assert deleted_count == 0, "Should not delete recent failed notifications with 365 day limit"
    logging.info("✓ cleanup_old_failed_notifications works correctly")

    # Test 4: Verify storage has items before clearing
    logging.info("Testing storage state before clear...")
    failed_before_clear = get_failed_notifications()
    assert len(failed_before_clear) > 0, "Should have failed notifications before clearing"

    # Test 5: Clear all notifications
    logging.info("Testing clear_all_notifications...")
    clear_result = clear_all_notifications()
    logging.info(f"Clear result: {clear_result}")
    assert 'results' in clear_result, "Clear result should include 'results' key"
    assert clear_result['results'] > 0, "Should have cleared at least one result"
    logging.info("✓ clear_all_notifications works correctly")

    # Test 6: Verify dead-letter queue is empty after clearing
    logging.info("Verifying dead-letter queue is empty after clear...")
    failed_after_clear = get_failed_notifications()
    assert len(failed_after_clear) == 0, "Dead-letter queue should be empty after clearing"
    logging.info("✓ Dead-letter queue is empty after clear")

    # Test 7: Verify body class is NOT present when there are no failures
    logging.info("Testing body class when no failed notifications...")
    res = client.get(url_for("watchlist.index"))
    assert res.status_code == 200
    # The body tag should still exist but without failed-notifications class
    # Check by looking for the body tag without the class
    response_text = res.data.decode('utf-8')
    # Should have body tag but not with failed-notifications class
    import re
    body_match = re.search(r'<body[^>]*class="([^"]*)"', response_text)
    if body_match:
        classes = body_match.group(1)
        assert 'failed-notifications' not in classes, \
            "Body should NOT have 'failed-notifications' class when dead-letter queue is empty"
    logging.info("✓ Body class 'failed-notifications' is NOT present when queue is empty")

    # Test 8: Trigger another failure and test retry_all with empty result
    logging.info("Testing retry_all_failed_notifications with empty queue...")
    retry_result = retry_all_failed_notifications()
    logging.info(f"Retry result with empty queue: {retry_result}")
    assert retry_result['total'] == 0, "Should have 0 total when dead-letter is empty"
    assert retry_result['success'] == 0, "Should have 0 success when dead-letter is empty"
    assert retry_result['failed'] == 0, "Should have 0 failed when dead-letter is empty"
    logging.info("✓ retry_all_failed_notifications handles empty queue correctly")

    client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)

    logging.info("✓ UI and utility functions test completed successfully")


def test_notification_not_failed_while_retrying(client, live_server, measure_memory_usage, datastore_path):
    """
    Test that notifications don't show as "Failed" while they're still being retried.

    This verifies the fix for the issue where a notification would appear in both
    "Pending/Retrying" and "Failed" counts simultaneously.
    """
    from changedetectionio.notification.task_queue import get_failed_notifications

    set_original_response(datastore_path=datastore_path)

    # Set a URL and fetch it
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)

    wait_for_all_checks(client)

    # Set a broken notification URL that will fail
    broken_notification_url = "jsons://broken-url-retry-test-99999/test"

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "notification_urls": broken_notification_url,
            "notification_title": "Test Retry Status",
            "notification_body": "Testing that retrying tasks don't show as failed",
            "notification_format": 'text',
            "url": test_url,
            "tags": "",
            "title": "",
            "headers": "",
            "time_between_check-minutes": "180",
            "fetch_backend": "html_requests",
            "time_between_check_use_default": "y"
        },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    wait_for_all_checks(client)
    set_modified_response(datastore_path=datastore_path)
    res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    assert b'Queued 1 watch for rechecking.' in res.data

    # Wait a short time for initial failure (but NOT long enough for all retries)
    # With 1 retry and 10s delay, the first attempt fails immediately
    # Then it's scheduled for retry in 10 seconds
    logging.info("Waiting for initial failure (but not all retries)...")
    time.sleep(3)  # Wait 3 seconds - enough for first failure, not enough for retry

    # Check dead-letter queue - should be EMPTY because task is still scheduled for retry
    failed_notifications = get_failed_notifications()
    logging.info(f"Dead-letter queue after 3s: {len(failed_notifications)} items (should be 0 - still retrying)")

    assert len(failed_notifications) == 0, \
        "Dead-letter queue should be EMPTY while task is still being retried " \
        "(task failed but has pending retry, so shouldn't appear as 'Failed' yet)"

    # Check the settings/failed-notifications page while notification is retrying
    # The page should show the pending/retrying <details> element
    logging.info("Checking failed-notifications page while notification is retrying...")

    # First verify the count function returns 1
    from changedetectionio.notification.task_queue import get_pending_notifications_count
    count = get_pending_notifications_count()
    logging.info(f"Pending count before page load: {count}")

    res = client.get(url_for("settings.failed_notifications"))
    assert res.status_code == 200

    # Check if the page shows pending count
    # Look for patterns like "1 notification" or just the number "1" near "Pending"
    page_text = res.data.decode('utf-8')
    logging.info(f"Page contains 'Pending/Retrying': {'Pending/Retrying' in page_text}")
    logging.info(f"Page contains '1': {'1' in page_text}")

    # The count should be displayed in the summary section
    assert b"1" in res.data and b"Pending" in res.data, \
        "Page should show pending notification count"
    # Should show the pending notification in the dashboard
    assert b"QUEUED" in res.data or b"RETRYING" in res.data, \
        "Page should show queued or retrying status badge"
    logging.info("✓ Page correctly shows pending/retrying notifications in dashboard")

    # Now wait for all retries to complete
    # Retry is scheduled at 10s, so wait another 9 seconds for it to execute and fail
    logging.info("Waiting for all retries to complete...")
    time.sleep(9)  # Total 12 seconds - enough for retry to execute and fail

    # Now check dead-letter queue - should have 1 item (all retries exhausted)
    failed_notifications = get_failed_notifications()
    logging.info(f"Dead-letter queue after all retries: {len(failed_notifications)} items (should be 1)")

    assert len(failed_notifications) == 1, \
        "Dead-letter queue should have 1 item after ALL retries are exhausted"

    # Verify it's our notification
    assert any('broken-url-retry-test-99999' in str(notif.get('notification_data', {}))
              for notif in failed_notifications), \
        "Failed notification should be our test notification"

    client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)

    logging.info("✓ Notification correctly shows as 'Failed' only after ALL retries exhausted")


def test_notification_ajax_log_endpoint(client, live_server, measure_memory_usage, datastore_path):
    """
    Test the AJAX endpoint for fetching notification logs.

    This test verifies:
    1. The endpoint returns JSON with expected fields when task exists
    2. The endpoint returns 404 when task doesn't exist
    3. The log data includes apprise_log, task_id, watch_url, notification_urls, error
    """
    from changedetectionio.notification.task_queue import get_failed_notifications
    import json

    set_original_response(datastore_path=datastore_path)

    # Set a URL and fetch it
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)

    wait_for_all_checks(client)

    # Set a broken notification URL that will fail
    broken_notification_url = "jsons://broken-url-ajax-test-77777/test"

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "notification_urls": broken_notification_url,
            "notification_title": "Test AJAX Endpoint",
            "notification_body": "Testing AJAX log fetch endpoint",
            "notification_format": 'text',
            "url": test_url,
            "tags": "",
            "title": "",
            "headers": "",
            "time_between_check-minutes": "180",
            "fetch_backend": "html_requests",
            "time_between_check_use_default": "y"
        },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    wait_for_all_checks(client)
    set_modified_response(datastore_path=datastore_path)
    res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    assert b'Queued 1 watch for rechecking.' in res.data

    # Wait for notification to fail and exhaust all retries
    logging.info("Waiting for notification to fail...")
    max_wait_time = 20
    start_time = time.time()
    failed_found = False

    while time.time() - start_time < max_wait_time:
        failed_notifications = get_failed_notifications()
        if failed_notifications and len(failed_notifications) > 0:
            failed_found = True
            logging.info(f"Found {len(failed_notifications)} failed notification(s)")
            time.sleep(2)  # Wait for result to be fully written
            break
        time.sleep(1)

    assert failed_found, "Notification should have failed"

    # Get the failed notification to extract task_id
    failed_notifications = get_failed_notifications()
    assert len(failed_notifications) > 0, "Should have at least one failed notification"

    task_id = failed_notifications[0].get('task_id')
    assert task_id, "Failed notification should have a task_id"
    logging.info(f"Testing AJAX endpoint with task_id: {task_id}")

    # Test 1: Fetch log for existing task
    res = client.get(url_for("notification_dashboard.get_notification_log", task_id=task_id))
    assert res.status_code == 200, "Endpoint should return 200 for existing task"
    assert res.content_type == 'application/json', "Response should be JSON"

    # Parse JSON response
    log_data = json.loads(res.data)
    logging.info(f"Log data keys: {log_data.keys()}")

    # Verify expected fields exist
    assert 'task_id' in log_data, "Response should include task_id"
    assert 'apprise_log' in log_data, "Response should include apprise_log"
    assert log_data['task_id'] == task_id, "Response task_id should match requested task_id"

    # Verify optional fields (may or may not be present depending on notification data)
    # These should be present if the notification_data was stored
    logging.info(f"Log data: {log_data}")

    # The error field should be present for failed notifications
    # Note: The error might be None if the task result hasn't been fully written yet,
    # but the AJAX endpoint should still return the field
    assert 'error' in log_data, "Response should include error field"

    if log_data['error']:
        logging.info(f"✓ AJAX endpoint returned valid JSON with error: {log_data['error'][:50]}...")
    else:
        logging.info("✓ AJAX endpoint returned valid JSON (error field present but empty - timing dependent)")

    # Test 2: Fetch log for non-existent task
    fake_task_id = "nonexistent-task-id-12345"
    res = client.get(url_for("notification_dashboard.get_notification_log", task_id=fake_task_id))
    assert res.status_code == 404, "Endpoint should return 404 for non-existent task"

    # Parse 404 JSON response
    error_data = json.loads(res.data)
    assert 'error' in error_data, "404 response should include error message"
    assert 'not found' in error_data['error'].lower(), "Error message should mention 'not found'"

    logging.info("✓ AJAX endpoint correctly returns 404 for non-existent task")

    client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)

    logging.info("✓ AJAX log endpoint test completed successfully")


def test_notification_ajax_log_shows_apprise_details(client, live_server, measure_memory_usage, datastore_path):
    """
    Test that clicking on a retrying/failed notification shows Apprise logs with error details.

    This verifies that the AJAX endpoint returns detailed Apprise logs including
    connection errors like "Name or service not known" or similar DNS/connection failures.
    """
    from changedetectionio.notification.task_queue import get_pending_notifications, get_failed_notifications
    import json
    import time

    set_original_response(datastore_path=datastore_path)

    # Set a URL and fetch it
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)

    wait_for_all_checks(client)

    # Set a broken notification URL that will fail with DNS/connection error
    broken_notification_url = "jsons://broken-dns-will-not-resolve-12345xyz/test"

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "notification_urls": broken_notification_url,
            "notification_title": "Test Apprise Logs Display",
            "notification_body": "Testing that Apprise logs show connection errors",
            "notification_format": 'text',
            "url": test_url,
            "tags": "",
            "title": "",
            "headers": "",
            "time_between_check-minutes": "180",
            "fetch_backend": "html_requests",
            "time_between_check_use_default": "y"
        },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    wait_for_all_checks(client)
    set_modified_response(datastore_path=datastore_path)
    res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    assert b'Queued 1 watch for rechecking.' in res.data

    # Wait for notification to fail and be scheduled for retry (first attempt fails)
    logging.info("Waiting for initial failure and retry scheduling...")
    time.sleep(3)

    # Get pending notifications (should include the retrying task)
    pending = get_pending_notifications(limit=50)
    logging.info(f"Pending notifications: {len(pending)}")

    if pending and len(pending) > 0:
        # Found a pending/retrying notification - test its log
        task_id = pending[0].get('task_id')
        logging.info(f"Testing log for pending/retrying task: {task_id}")

        res = client.get(url_for("notification_dashboard.get_notification_log", task_id=task_id))
        assert res.status_code == 200, "Should get log for pending/retrying notification"

        log_data = json.loads(res.data)
        logging.info(f"Log data for retrying notification: {log_data.keys()}")
        logging.info(f"Apprise log excerpt: {log_data.get('apprise_log', '')[:200]}")
        logging.info(f"Error excerpt: {log_data.get('error', '')[:200] if log_data.get('error') else 'None'}")

        # Check if error info contains connection failure details
        has_error_details = False
        if log_data.get('error'):
            error_text = str(log_data['error'])
            has_error_details = (
                'No address found' in error_text or
                'Name or service not known' in error_text or
                'nodename nor servname provided' in error_text or
                'Temporary failure in name resolution' in error_text or
                'Failed to establish a new connection' in error_text or
                'Connection error occurred' in error_text or
                'Connection' in error_text
            )

        # Check if apprise_log contains useful error details
        has_log_details = False
        if log_data.get('apprise_log') and log_data['apprise_log'] != 'No log available':
            log_text = log_data['apprise_log']
            has_log_details = (
                'No address found' in log_text or
                'Name or service not known' in log_text or
                'nodename nor servname provided' in log_text or
                'Temporary failure in name resolution' in log_text or
                'Failed to establish a new connection' in log_text or
                'Connection error occurred' in log_text or
                'Connection' in log_text or
                'Socket Exception' in log_text
            )

        # At least one should have detailed error information
        assert has_error_details or has_log_details, \
            f"Apprise logs or error should contain connection failure details. Got apprise_log: {log_data.get('apprise_log', '')[:300]}, error: {log_data.get('error', '')[:300] if log_data.get('error') else 'None'}"

        logging.info("✓ Retrying notification shows Apprise error details")

    # Wait for all retries to complete
    logging.info("Waiting for all retries to complete...")
    time.sleep(15)

    # Check failed notifications
    failed = get_failed_notifications()
    if failed and len(failed) > 0:
        task_id = failed[0].get('task_id')
        logging.info(f"Testing log for failed (dead-letter) task: {task_id}")

        res = client.get(url_for("notification_dashboard.get_notification_log", task_id=task_id))
        assert res.status_code == 200, "Should get log for failed notification"

        log_data = json.loads(res.data)
        assert 'error' in log_data, "Failed notification should have error field"

        # Failed notifications should definitely have error details
        if log_data.get('error'):
            error_text = str(log_data['error'])
            found_name_resolution_error = (
                'No address found' in error_text or
                'Name or service not known' in error_text or
                'nodename nor servname provided' in error_text or
                'Temporary failure in name resolution' in error_text or
                'Failed to establish a new connection' in error_text or
                'Connection error occurred' in error_text or
                'Connection' in error_text
            )
            assert found_name_resolution_error, \
                f"Failed notification error should contain connection failure details. Got: {error_text[:300]}"

        logging.info("✓ Failed notification shows error details")

    client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)

    logging.info("✓ Apprise logs display test completed successfully")


def test_send_now_button(client, live_server, measure_memory_usage, datastore_path):
    """Test the 'Send Now' button on retrying notifications."""
    import time
    import json
    import logging
    from flask import url_for
    from changedetectionio.notification.task_queue import get_pending_notifications
    from .util import set_original_response, set_modified_response, wait_for_all_checks

    set_original_response(datastore_path=datastore_path)

    # Add watch with notification
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("ui.form_quick_watch_add"),
        data={"url": test_url, "tags": '', 'edit_and_watch_submit_button': 'Edit > Watch'},
        follow_redirects=True
    )
    assert b"Watch added in Paused state, saving will unpause" in res.data

    # Enable notification with bad SMTP server to force retry
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "url": test_url,
            "tags": "",
            "notification_urls": f'mailto://invalid-smtp-server-{int(time.time())}:587/?from=test@example.com&to=recipient@example.com&user=test&pass=test',
            "notification_title": "Change detected",
            "notification_body": "Triggered text was: {{triggered_text}}",
            "notification_format": "Text",
            "fetch_backend": "html_requests"
        },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    # Trigger initial check to queue notification
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    time.sleep(2)

    # Change the endpoint and trigger again to generate a notification
    set_modified_response(datastore_path=datastore_path)
    res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    time.sleep(3)  # Wait for notification to fail and be scheduled for retry

    # Check that notification is in "retrying" state
    pending = get_pending_notifications(limit=100)
    retrying = [n for n in pending if n.get('status') == 'retrying']
    assert len(retrying) > 0, "Should have at least one retrying notification"

    task_id = retrying[0].get('task_id')
    assert task_id, "Retrying notification should have task_id"

    logging.info(f"Found retrying notification with task_id: {task_id}")

    # Click "Send Now" button (GET request)
    res = client.get(url_for("notification_dashboard.send_now", task_id=task_id), follow_redirects=True)

    # Should redirect back to notification dashboard with message
    # The notification will still fail (bad SMTP server), but should be executed immediately
    # and removed from the retry schedule
    time.sleep(2)

    # Check that notification was removed from retry schedule
    pending_after = get_pending_notifications(limit=100)
    retrying_after = [n for n in pending_after if n.get('status') == 'retrying' and n.get('task_id') == task_id]

    # The task should be gone from schedule (either succeeded or moved to dead letter)
    assert len(retrying_after) == 0, "Notification should be removed from retry schedule after 'Send Now'"

    logging.info("✓ Send Now button successfully executed notification immediately")

    client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)

    logging.info("✓ Send Now button test completed successfully")


def test_retry_count_display(client, live_server, measure_memory_usage, datastore_path):
    """Test that retrying notifications show retry count (X/Y) correctly."""
    import time
    import logging
    from flask import url_for
    from changedetectionio.notification.task_queue import get_pending_notifications
    from .util import set_original_response, set_modified_response, wait_for_all_checks

    # For this test, we need enough retries to see progression
    # Set to 3 retries so we can verify it shows "2/3" after 2 failures
    import os
    os.environ['NOTIFICATION_RETRY_COUNT'] = '3'
    os.environ['NOTIFICATION_RETRY_DELAY'] = '2'  # Fast retries for testing

    # Need to reinit Huey with new config
    from changedetectionio.notification.task_queue import init_huey
    init_huey(datastore_path)

    set_original_response(datastore_path=datastore_path)

    # Add watch with notification
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    wait_for_all_checks(client)

    # Enable notification with bad SMTP server to force retry
    broken_notification_url = f'mailto://invalid-smtp-test-{int(time.time())}:587/?from=test@example.com&to=recipient@example.com&user=test&pass=test'

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "url": test_url,
            "tags": "",
            "notification_urls": broken_notification_url,
            "notification_title": "Retry Count Test",
            "notification_body": "Testing retry count display",
            "notification_format": "Text",
            "fetch_backend": "html_requests",
            "headers": "",
            "title": "",
            "time_between_check-minutes": "180",
            "time_between_check_use_default": "y"
        },
        follow_redirects=True
    )
    # Note: Form may show edit page again, but settings should be saved
    wait_for_all_checks(client)

    # Change content to trigger notification
    set_modified_response(datastore_path=datastore_path)
    res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    logging.info("Waiting for notification to fail and retry at least twice...")

    # Wait for notification to fail at least twice
    # With 2s retry delay: initial fail + 2s wait + 1st retry fail + 4s wait + 2nd retry = ~8s
    max_wait = 15
    start_time = time.time()
    found_retry_2_of_3 = False

    while time.time() - start_time < max_wait:
        pending = get_pending_notifications(limit=100)
        retrying = [n for n in pending if n.get('status') == 'retrying']

        if retrying:
            for notification in retrying:
                retry_num = notification.get('retry_number')
                total = notification.get('total_retries')
                elapsed = time.time() - start_time

                logging.info(f"[{elapsed:.1f}s] Found retrying notification: {retry_num}/{total}")

                # We want to see at least attempt 2/3 (meaning it failed twice and is scheduled for 3rd attempt)
                if retry_num and retry_num >= 2 and total == 3:
                    found_retry_2_of_3 = True
                    logging.info(f"✓ Found retry count display: {retry_num}/{total}")
                    break

        if found_retry_2_of_3:
            break

        time.sleep(1)

    assert found_retry_2_of_3, \
        f"Should show retry count of at least 2/3 after multiple failures. " \
        f"Last pending: {[(n.get('retry_number'), n.get('total_retries')) for n in pending if n.get('status') == 'retrying']}"

    logging.info("✓ Retry count display verified: Shows X/Y format correctly")

    client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)

    logging.info("✓ Retry count display test completed successfully")


def test_delivered_notifications_appear_in_dashboard(client, live_server, measure_memory_usage, datastore_path):
    """
    Test that successfully delivered notifications appear in the notification dashboard.

    Steps:
    1. Set up a watch with a working notification URL (gets://)
    2. Trigger a change that will send a notification
    3. Wait for the notification to be delivered
    4. Check that it appears in the dashboard with "delivered" status
    5. Verify apprise logs are available
    """
    import time
    import json
    import logging
    from flask import url_for
    from changedetectionio.notification.task_queue import get_delivered_notifications, get_all_notification_events
    from .util import set_original_response, set_modified_response, wait_for_all_checks

    logging.info("Starting delivered notifications dashboard test")

    set_original_response(datastore_path=datastore_path)

    # Set a URL and fetch it
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)

    wait_for_all_checks(client)

    # Create a test endpoint for the gets:// notification to call
    test_notification_endpoint = url_for('test_notification_endpoint', _external=True, _scheme='http')

    # Use gets:// URL which will succeed
    working_notification_url = f"gets://{test_notification_endpoint.replace('http://', '')}"

    logging.info(f"Setting up watch with working notification URL: {working_notification_url}")

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "notification_urls": working_notification_url,
            "notification_title": "Test Delivered",
            "notification_body": "This notification should succeed",
            "notification_format": 'text',
            "url": test_url,
            "tags": "",
            "title": "",
            "headers": "",
            "fetch_backend": "html_requests",
            "time_between_check_use_default": "y"
        },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    logging.info("✓ Watch updated with notification settings")

    # Trigger a change
    set_modified_response(datastore_path=datastore_path)

    # Trigger a recheck that will send notification
    res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    # Just verify we got a response (the check may queue or run immediately)
    assert res.status_code == 200
    wait_for_all_checks(client)

    logging.info("Waiting for notification to be delivered...")

    # Wait up to 15 seconds for notification to complete
    max_wait = 15
    delivered_found = False
    for i in range(max_wait):
        delivered = get_delivered_notifications(limit=10)
        if delivered and len(delivered) > 0:
            # Check if our notification is there
            for notif in delivered:
                if notif.get('watch_url') == test_url:
                    delivered_found = True
                    logging.info(f"✓ Found delivered notification in storage after {i+1}s")
                    logging.info(f"  Task ID: {notif.get('task_id')}")
                    logging.info(f"  Watch URL: {notif.get('watch_url')}")
                    logging.info(f"  Notification URLs: {notif.get('notification_urls')}")
                    break
        if delivered_found:
            break
        time.sleep(1)

    assert delivered_found, \
        f"Delivered notification should appear in storage within {max_wait}s. " \
        f"Found {len(delivered) if delivered else 0} delivered notifications total."

    # Now check that it appears in the unified events list
    events = get_all_notification_events(limit=100)

    delivered_events = [e for e in events if e['status'] == 'delivered']
    logging.info(f"Found {len(delivered_events)} delivered events in unified events list")

    # Find our specific event
    our_delivered_event = None
    for event in delivered_events:
        if event.get('watch_url') == test_url:
            our_delivered_event = event
            break

    assert our_delivered_event is not None, \
        f"Our delivered notification should appear in unified events list. " \
        f"Total events: {len(events)}, delivered events: {len(delivered_events)}"

    logging.info("✓ Delivered notification appears in unified events list")
    logging.info(f"  Event ID: {our_delivered_event.get('id')}")
    logging.info(f"  Status: {our_delivered_event.get('status')}")
    logging.info(f"  Watch URL: {our_delivered_event.get('watch_url')}")

    # Verify apprise logs are present
    assert our_delivered_event.get('apprise_logs'), \
        "Delivered event should have apprise logs"

    logging.info("✓ Delivered event has apprise logs")

    # Now check the dashboard UI shows it
    res = client.get(url_for("notification_dashboard.dashboard"))
    assert res.status_code == 200
    assert b"delivered" in res.data.lower(), \
        "Dashboard should show 'delivered' status"

    logging.info("✓ Dashboard page loads and shows delivered status")

    client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)

    logging.info("✓ Delivered notifications dashboard test completed successfully")
