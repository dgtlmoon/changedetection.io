import os
import time
import re
from flask import url_for
from . util import set_original_response, set_modified_response, live_server_setup
import logging

def test_check_notification_error_handling(client, live_server):

    live_server_setup(live_server)
    set_original_response()

    # Give the endpoint time to spin up
    time.sleep(2)

    # Set a URL and fetch it, then set a notification URL which is going to give errors
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("form_quick_watch_add"),
        data={"url": test_url, "tag": ''},
        follow_redirects=True
    )
    assert b"Watch added" in res.data

    time.sleep(2)
    set_modified_response()

    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"notification_urls": "jsons://broken-url-xxxxxxxx123/test",
              "notification_title": "xxx",
              "notification_body": "xxxxx",
              "notification_format": "Text",
              "url": test_url,
              "tag": "",
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
            url_for("index"))

        if bytes("Notification error detected".encode('utf-8')) in res.data:
            found=True
            break

        time.sleep(1)

    assert found


    # The error should show in the notification logs
    res = client.get(
        url_for("notification_logs"))
    found_name_resolution_error = b"Temporary failure in name resolution" in res.data or b"Name or service not known" in res.data
    assert found_name_resolution_error

    client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
