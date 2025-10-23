import time
from flask import url_for
from email import message_from_string
from email.policy import default as email_policy

from changedetectionio.diff import REMOVED_STYLE, ADDED_STYLE
from changedetectionio.tests.util import set_original_response, set_modified_response, set_more_modified_response, live_server_setup, \
    wait_for_all_checks, \
    set_longer_modified_response, delete_all_watches

import logging


# NOTE - RELIES ON mailserver as hostname running, see github build recipes
smtp_test_server = 'localhost'

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
              "application-notification_body": "some text\nfallback-body<br> " + default_notification_body,
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

    msg_raw = get_last_message_from_smtp_server()
    assert len(msg_raw) >= 1

    # Parse the email properly using Python's email library
    msg = message_from_string(msg_raw, policy=email_policy)

    # The email should have two bodies (multipart/alternative with text/plain and text/html)
    assert msg.is_multipart()
    assert msg.get_content_type() == 'multipart/alternative'

    # Get the parts
    parts = list(msg.iter_parts())
    assert len(parts) == 2

    # First part should be text/plain (the auto-generated plaintext version)
    text_part = parts[0]
    assert text_part.get_content_type() == 'text/plain'
    text_content = text_part.get_content()
    assert '(added) So let\'s see what happens.\r\n' in text_content  # The plaintext part
    assert 'fallback-body\r\n' in text_content  # The plaintext part

    # Second part should be text/html
    html_part = parts[1]
    assert html_part.get_content_type() == 'text/html'
    html_content = html_part.get_content()
    assert 'some text<br>' in html_content  # We converted \n from the notification body
    assert 'fallback-body<br>' in html_content  # kept the original <br>
    assert '(added) So let\'s see what happens.<br>' in html_content  # the html part
    delete_all_watches(client)


def test_check_notification_plaintext_format(client, live_server, measure_memory_usage):
    set_original_response()

    notification_url = f'mailto://changedetection@{smtp_test_server}:11025/?to=fff@home.com'

    #####################
    # Set this up for when we remove the notification from the watch, it should fallback with these details
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-notification_urls": notification_url,
              "application-notification_title": "fallback-title " + default_notification_title,
              "application-notification_body": "some text\n" + default_notification_body,
              "application-notification_format": 'Text',
              "requests-time_between_check-minutes": 180,
              'application-fetch_backend': "html_requests"},
        follow_redirects=True
    )

    assert b"Settings updated." in res.data

    # Add a watch and trigger a HTTP POST
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    time.sleep(2)

    set_longer_modified_response()
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    time.sleep(3)

    msg_raw = get_last_message_from_smtp_server()
    assert len(msg_raw) >= 1

    # Parse the email properly using Python's email library
    msg = message_from_string(msg_raw, policy=email_policy)

    # The email should be plain text only (not multipart)
    assert not msg.is_multipart()
    assert msg.get_content_type() == 'text/plain'

    # Get the plain text content
    text_content = msg.get_content()
    assert '(added) So let\'s see what happens.\r\n' in text_content  # The plaintext part

    # Should NOT contain HTML
    assert '<br>' not in text_content  # We should not have HTML in plain text
    delete_all_watches(client)



def test_check_notification_html_color_format(client, live_server, measure_memory_usage):
    set_original_response()

    notification_url = f'mailto://changedetection@{smtp_test_server}:11025/?to=fff@home.com'

    #####################
    # Set this up for when we remove the notification from the watch, it should fallback with these details
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-notification_urls": notification_url,
              "application-notification_title": "fallback-title " + default_notification_title,
              "application-notification_body": "some text\n" + default_notification_body,
              "application-notification_format": 'HTML Color',
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

    msg_raw = get_last_message_from_smtp_server()
    assert len(msg_raw) >= 1

    # Parse the email properly using Python's email library
    msg = message_from_string(msg_raw, policy=email_policy)

    # The email should have two bodies (multipart/alternative with text/plain and text/html)
    assert msg.is_multipart()
    assert msg.get_content_type() == 'multipart/alternative'

    # Get the parts
    parts = list(msg.iter_parts())
    assert len(parts) == 2

    # First part should be text/plain (the auto-generated plaintext version)
    text_part = parts[0]
    assert text_part.get_content_type() == 'text/plain'
    text_content = text_part.get_content()
    assert 'So let\'s see what happens.\r\n' in text_content  # The plaintext part
    assert '(added)' not in text_content # Because apprise only dumb converts the html to text

    # Second part should be text/html with color styling
    html_part = parts[1]
    assert html_part.get_content_type() == 'text/html'
    html_content = html_part.get_content()
    assert REMOVED_STYLE in html_content
    assert ADDED_STYLE in html_content

    assert 'some text<br>' in html_content
    delete_all_watches(client)

def test_check_notification_markdown_format(client, live_server, measure_memory_usage):
    set_original_response()

    notification_url = f'mailto://changedetection@{smtp_test_server}:11025/?to=fff@home.com'

    #####################
    # Set this up for when we remove the notification from the watch, it should fallback with these details
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-notification_urls": notification_url,
              "application-notification_title": "fallback-title " + default_notification_title,
              "application-notification_body": "*header*\n\nsome text\n" + default_notification_body,
              "application-notification_format": 'Markdown to HTML',
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

    msg_raw = get_last_message_from_smtp_server()
    assert len(msg_raw) >= 1

    # Parse the email properly using Python's email library
    msg = message_from_string(msg_raw, policy=email_policy)

    # The email should have two bodies (multipart/alternative with text/plain and text/html)
    assert msg.is_multipart()
    assert msg.get_content_type() == 'multipart/alternative'

    # Get the parts
    parts = list(msg.iter_parts())
    assert len(parts) == 2

    # First part should be text/plain (the auto-generated plaintext version)
    text_part = parts[0]
    assert text_part.get_content_type() == 'text/plain'
    text_content = text_part.get_content()
    assert '(added) So let\'s see what happens.\r\n' in text_content  # The plaintext part


    # Second part should be text/html and roughly converted from markdown to HTML
    html_part = parts[1]
    assert html_part.get_content_type() == 'text/html'
    html_content = html_part.get_content()
    assert '<p><em>header</em></p>' in html_content
    assert '(added) So let\'s see what happens.<br' in html_content
    delete_all_watches(client)


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
    msg_raw = get_last_message_from_smtp_server()
    assert len(msg_raw) >= 1
    #    with open('/tmp/m.txt', 'w') as f:
    #        f.write(msg_raw)

    # Parse the email properly using Python's email library
    msg = message_from_string(msg_raw, policy=email_policy)

    # The email should not have two bodies, should be TEXT only
    assert not msg.is_multipart()
    assert msg.get_content_type() == 'text/plain'

    # Get the plain text content
    text_content = msg.get_content()
    assert '(added) So let\'s see what happens.\r\n' in text_content  # The plaintext part

    set_original_response()
    # Now override as HTML format
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "url": test_url,
            "notification_format": 'HTML',
            'fetch_backend': "html_requests",
            "time_between_check_use_default": "y"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    wait_for_all_checks(client)

    time.sleep(3)
    msg_raw = get_last_message_from_smtp_server()
    assert len(msg_raw) >= 1

    # Parse the email properly using Python's email library
    msg = message_from_string(msg_raw, policy=email_policy)

    # The email should have two bodies (multipart/alternative)
    assert msg.is_multipart()
    assert msg.get_content_type() == 'multipart/alternative'

    # Get the parts
    parts = list(msg.iter_parts())
    assert len(parts) == 2

    # First part should be text/plain
    text_part = parts[0]
    assert text_part.get_content_type() == 'text/plain'
    text_content = text_part.get_content()
    assert '(removed) So let\'s see what happens.\r\n' in text_content  # The plaintext part

    # Second part should be text/html
    html_part = parts[1]
    assert html_part.get_content_type() == 'text/html'
    html_content = html_part.get_content()
    assert '(removed) So let\'s see what happens.<br>' in html_content  # the html part

    # https://github.com/dgtlmoon/changedetection.io/issues/2103
    assert '<h1>Test</h1>' in html_content
    assert '&lt;' not in html_content

    delete_all_watches(client)
