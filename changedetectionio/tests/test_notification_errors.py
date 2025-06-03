import os
import time
from flask import url_for
from .util import set_original_response, set_modified_response, live_server_setup, wait_for_all_checks
import logging

def test_check_notification_error_handling(client, live_server, measure_memory_usage):

   #  live_server_setup(live_server) # Setup on conftest per function
    set_original_response()

    # Set a URL and fetch it, then set a notification URL which is going to give errors
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": ''},
        follow_redirects=True
    )
    assert b"Watch added" in res.data

    wait_for_all_checks(client)
    set_modified_response()

    working_notification_url = url_for('test_notification_endpoint', _external=True).replace('http', 'json')
    broken_notification_url = "jsons://broken-url-xxxxxxxx123/test"

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        # A URL with errors should not block the one that is working
        data={"notification_urls": f"{broken_notification_url}\r\n{working_notification_url}",
              "notification_title": "xxx",
              "notification_body": "xxxxx",
              "notification_format": "Text",
              "url": test_url,
              "tags": "",
              "title": "",
              "headers": "",
              "time_between_check-minutes": "180",
              "fetch_backend": "html_requests"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    found=False
    for i in range(1, 10):

        logging.debug("Fetching watch overview....")
        res = client.get(
            url_for("watchlist.index"))

        if bytes("Notification error detected".encode('utf-8')) in res.data:
            found=True
            break

        time.sleep(1)

    assert found


    # The error should show in the notification logs
    res = client.get(
        url_for("settings.notification_logs"))
    # Check for various DNS/connection error patterns that may appear in different environments
    found_name_resolution_error = (
        b"No address found" in res.data or 
        b"Name or service not known" in res.data or
        b"nodename nor servname provided" in res.data or
        b"Temporary failure in name resolution" in res.data or
        b"Failed to establish a new connection" in res.data or
        b"Connection error occurred" in res.data
    )
    assert found_name_resolution_error

    # And the working one, which is after the 'broken' one should still have fired
    with open("test-datastore/notification.txt", "r") as f:
        notification_submission = f.read()
    os.unlink("test-datastore/notification.txt")
    assert 'xxxxx' in notification_submission

    client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
