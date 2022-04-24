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
    time.sleep(3)

    # use a different URL so that it doesnt interfere with the actual check until we are ready
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("api_watch_add"),
        data={"url": "https://changedetection.io/CHANGELOG.txt", "tag": ''},
        follow_redirects=True
    )
    assert b"Watch added" in res.data

    time.sleep(10)

    # Check we capture the failure, we can just use trigger_check = y here
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"notification_urls": "jsons://broken-url.changedetection.io/test",
              "notification_title": "xxx",
              "notification_body": "xxxxx",
              "notification_format": "Text",
              "url": test_url,
              "tag": "",
              "title": "",
              "headers": "",
              "time_between_check-minutes": "180",
              "fetch_backend": "html_requests",
              "trigger_check": "y"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    found=False
    for i in range(1, 10):
        time.sleep(1)
        logging.debug("Fetching watch overview....")
        res = client.get(
            url_for("index"))

        if bytes("Notification error detected".encode('utf-8')) in res.data:
            found=True
            break


    assert found


    # The error should show in the notification logs
    res = client.get(
        url_for("notification_logs"))
    assert bytes("Name or service not known".encode('utf-8')) in res.data


    # And it should be listed on the watch overview
