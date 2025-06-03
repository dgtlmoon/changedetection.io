import json
import os
import time
import re
from flask import url_for
from changedetectionio.tests.util import set_original_response, set_modified_response, set_more_modified_response, live_server_setup, \
    wait_for_all_checks, \
    set_longer_modified_response
from changedetectionio.tests.util import extract_UUID_from_client
import logging
import base64

# NOTE - RELIES ON mailserver as hostname running, see github build recipes
smtp_test_server = 'mailserver'

from changedetectionio.notification import (
    default_notification_body,
    default_notification_format,
    default_notification_title,
    valid_notification_formats,
)



def get_last_message_from_smtp_server():
    import socket
    port = 11080  # socket server port number

    client_socket = socket.socket()  # instantiate
    client_socket.connect((smtp_test_server, port))  # connect to the server

    data = client_socket.recv(50024).decode()  # receive response
    logging.info("get_last_message_from_smtp_server..")
    logging.info(data)
    client_socket.close()  # close the connection
    return data


# Requires running the test SMTP server

def test_check_notification_email_formats_default_HTML(client, live_server, measure_memory_usage):
    ##  live_server_setup(live_server) # Setup on conftest per function
    set_original_response()

    notification_url = f'mailto://changedetection@{smtp_test_server}:11025/?to=fff@home.com'

    #####################
    # Set this up for when we remove the notification from the watch, it should fallback with these details
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-notification_urls": notification_url,
              "application-notification_title": "fallback-title " + default_notification_title,
              "application-notification_body": "fallback-body<br> " + default_notification_body,
              "application-notification_format": 'HTML',
              "requests-time_between_check-minutes": 180,
              'application-fetch_backend': "html_requests"},
        follow_redirects=True
    )
    assert b"Settings updated." in res.data

    # Add a watch and trigger a HTTP POST
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": 'nice one'},
        follow_redirects=True
    )

    assert b"Watch added" in res.data

    wait_for_all_checks(client)
    set_longer_modified_response()
    time.sleep(2)

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    time.sleep(3)

    msg = get_last_message_from_smtp_server()
    assert len(msg) >= 1

    # The email should have two bodies, and the text/html part should be <br>
    assert 'Content-Type: text/plain' in msg
    assert '(added) So let\'s see what happens.\r\n' in msg  # The plaintext part with \r\n
    assert 'Content-Type: text/html' in msg
    assert '(added) So let\'s see what happens.<br>' in msg  # the html part
    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data


def test_check_notification_email_formats_default_Text_override_HTML(client, live_server, measure_memory_usage):
    ##  live_server_setup(live_server) # Setup on conftest per function

    # HTML problems? see this
    # https://github.com/caronc/apprise/issues/633

    set_original_response()
    notification_url = f'mailto://changedetection@{smtp_test_server}:11025/?to=fff@home.com'
    notification_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <title>My Webpage</title>
</head>
<body>
    <h1>Test</h1>
    {default_notification_body}
</body>
</html>
"""

    #####################
    # Set this up for when we remove the notification from the watch, it should fallback with these details
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-notification_urls": notification_url,
              "application-notification_title": "fallback-title " + default_notification_title,
              "application-notification_body": notification_body,
              "application-notification_format": 'Text',
              "requests-time_between_check-minutes": 180,
              'application-fetch_backend': "html_requests"},
        follow_redirects=True
    )
    assert b"Settings updated." in res.data

    # Add a watch and trigger a HTTP POST
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": 'nice one'},
        follow_redirects=True
    )

    assert b"Watch added" in res.data

    wait_for_all_checks(client)
    set_longer_modified_response()
    time.sleep(2)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    time.sleep(3)
    msg = get_last_message_from_smtp_server()
    assert len(msg) >= 1
    #    with open('/tmp/m.txt', 'w') as f:
    #        f.write(msg)

    # The email should not have two bodies, should be TEXT only

    assert 'Content-Type: text/plain' in msg
    assert '(added) So let\'s see what happens.\r\n' in msg  # The plaintext part with \r\n

    set_original_response()
    # Now override as HTML format
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "url": test_url,
            "notification_format": 'HTML',
            'fetch_backend': "html_requests"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    wait_for_all_checks(client)

    time.sleep(3)
    msg = get_last_message_from_smtp_server()
    assert len(msg) >= 1

    # The email should have two bodies, and the text/html part should be <br>
    assert 'Content-Type: text/plain' in msg
    assert '(removed) So let\'s see what happens.\r\n' in msg  # The plaintext part with \n
    assert 'Content-Type: text/html' in msg
    assert '(removed) So let\'s see what happens.<br>' in msg  # the html part

    # https://github.com/dgtlmoon/changedetection.io/issues/2103
    assert '<h1>Test</h1>' in msg
    assert '&lt;' not in msg
    assert 'Content-Type: text/html' in msg

    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data
