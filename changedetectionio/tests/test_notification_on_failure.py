#!/usr/bin/python3

import os
import time
from pathlib import Path
from typing import Optional

from flask import url_for

from .util import live_server_setup, wait_for_all_checks

NOTIFICATION_PATH = Path("test-datastore/notification.txt")
ENDPOINT_CONTENT_PATH = Path("test-datastore/endpoint-content.txt")


def test_setup(live_server):
    live_server_setup(live_server)


def test_notification_on_failure(client, live_server):
    # Set the response
    ENDPOINT_CONTENT_PATH.write_text('test endpoint content\n')
    # Successful request does not trigger a notification
    preview = run_filter_test(client, test_url=url_for('test_endpoint', _external=True), expected_notification=None)
    assert 'test endpoint content' in preview.text
    # Failed request triggers a notification
    preview = run_filter_test(client, test_url=url_for('test_endpoint', _external=True, status_code=403),
                              expected_notification="Access denied")
    assert 'Error Text' in preview.text


def test_notification_on_failure_does_not_trigger_if_disabled(client, live_server):
    # Set the response
    ENDPOINT_CONTENT_PATH.write_text('test endpoint content\n')

    # Successful request does not trigger a notification
    preview = run_filter_test(client, test_url=url_for('test_endpoint', _external=True), expected_notification=None,
                              enable_notification_on_failure=False)
    assert 'test endpoint content' in preview.text

    # Failed request does not trigger a notification either
    preview = run_filter_test(client, test_url=url_for('test_endpoint', _external=True, status_code=403),
                              expected_notification=None, enable_notification_on_failure=False)
    assert 'Error Text' in preview.text


def expect_notification(expected_text):
    if expected_text is None:
        assert not NOTIFICATION_PATH.exists(), "Expected no notification, but found one"
    else:
        assert NOTIFICATION_PATH.exists(), "Expected notification, but found none"
        notification = NOTIFICATION_PATH.read_text()
        assert expected_text in notification, (f"Expected notification to contain '{expected_text}' but it did not. "
                                               f"Notification: {notification}")

    NOTIFICATION_PATH.unlink(missing_ok=True)


def run_filter_test(client, test_url: str, expected_notification: Optional[str], enable_notification_on_failure=True):
    # Set up the watch
    _setup_watch(client, test_url, enable_notification_on_failure=enable_notification_on_failure)

    # Ensure that the watch has been triggered
    wait_for_all_checks(client)

    # Give the thread time to pick it up
    time.sleep(3)

    # Check the notification
    expect_notification(expected_notification)

    res = client.get(
        url_for("preview_page", uuid="first"),
        follow_redirects=True
    )

    # TODO Move to pytest?
    cleanup(client)

    return res


def cleanup(client):
    # cleanup for the next test
    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data
    NOTIFICATION_PATH.unlink(missing_ok=True)


def _trigger_watch(client):
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)


def _setup_watch(client, test_url, enable_notification_on_failure=True):
    # Give the endpoint time to spin up
    time.sleep(1)
    # cleanup for the next
    client.get(
        url_for("form_delete", uuid="all"),
        follow_redirects=True
    )
    if os.path.isfile("test-datastore/notification.txt"):
        os.unlink("test-datastore/notification.txt")
    # Add our URL to the import page
    res = client.post(
        url_for("form_quick_watch_add"),
        data={"url": test_url, "tags": ''},
        follow_redirects=True
    )
    assert b"Watch added" in res.data
    # Give the thread time to pick up the first version
    wait_for_all_checks(client)
    # Goto the edit page, add our ignore text
    # Add our URL to the import page
    url = url_for('test_notification_endpoint', _external=True)
    notification_url = url.replace('http', 'json')
    print(">>>> Notification URL: " + notification_url)
    # Just a regular notification setting, this will be used by the special 'filter not found' notification
    notification_form_data = {"notification_urls": notification_url,
                              "notification_title": "New ChangeDetection.io Notification - {{watch_url}}",
                              "notification_body": "BASE URL: {{base_url}}\n"
                                                   "Watch URL: {{watch_url}}\n"
                                                   "Watch UUID: {{watch_uuid}}\n"
                                                   "Watch title: {{watch_title}}\n"
                                                   "Watch tag: {{watch_tag}}\n"
                                                   "Preview: {{preview_url}}\n"
                                                   "Diff URL: {{diff_url}}\n"
                                                   "Snapshot: {{current_snapshot}}\n"
                                                   "Diff: {{diff}}\n"
                                                   "Diff Full: {{diff_full}}\n"
                                                   "Diff as Patch: {{diff_patch}}\n"
                                                   ":-)",
                              "notification_format": "Text"}
    notification_form_data.update({
        "url": test_url,
        "title": "Notification test",
        "filter_failure_notification_send": '',
        "notification_notify_on_failure": 'y' if enable_notification_on_failure else '',
        "time_between_check-minutes": "180",
        "fetch_backend": "html_requests"})

    res = client.post(
        url_for("edit_page", uuid="first"),
        data=notification_form_data,
        follow_redirects=True
    )

    assert b"Updated watch." in res.data
