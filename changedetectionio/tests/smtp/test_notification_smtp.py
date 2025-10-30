import time
from flask import url_for
from email import message_from_string
from email.policy import default as email_policy

from changedetectionio.diff import HTML_REMOVED_STYLE, HTML_ADDED_STYLE, HTML_CHANGED_STYLE, REMOVED_PLACEMARKER_OPEN, \
    CHANGED_PLACEMARKER_OPEN, ADDED_PLACEMARKER_OPEN
from changedetectionio.notification_service import NotificationContextData
from changedetectionio.tests.util import set_original_response, set_modified_response, set_more_modified_response, live_server_setup, \
    wait_for_all_checks, \
    set_longer_modified_response, delete_all_watches

import logging


# NOTE - RELIES ON mailserver as hostname running, see github build recipes
smtp_test_server = 'mailserver'

ALL_MARKUP_TOKENS = ''.join(f"TOKEN: '{t}'\n{{{{{t}}}}}\n" for t in NotificationContextData().keys())

from changedetectionio.notification import (
    default_notification_body,
    default_notification_format,
    default_notification_title,
    valid_notification_formats,
)



def get_last_message_from_smtp_server():
    import requests
    time.sleep(1) # wait for any smtp connects to die off
    port = 11080  # HTTP server port number
    # Make HTTP GET request to Flask server
    response = requests.get(f'http://{smtp_test_server}:{port}/')
    data = response.text
    logging.info("get_last_message_from_smtp_server..")
    logging.info(data)
    return data


# Requires running the test SMTP server

def test_check_notification_email_formats_default_HTML(client, live_server, measure_memory_usage, datastore_path):
    ##  live_server_setup(live_server) # Setup on conftest per function
    set_original_response(datastore_path=datastore_path)


    notification_url = f'mailto://changedetection@{smtp_test_server}:11025/?to=fff@home.com'

    #####################
    # Set this up for when we remove the notification from the watch, it should fallback with these details
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-notification_urls": notification_url,
              "application-notification_title": "fallback-title " + default_notification_title,
              "application-notification_body": "some text\nfallback-body<br> " + default_notification_body,
              "application-notification_format": 'html',
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
    set_longer_modified_response(datastore_path=datastore_path)
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


def test_check_notification_plaintext_format(client, live_server, measure_memory_usage, datastore_path):
    set_original_response(datastore_path=datastore_path)


    notification_url = f'mailto://changedetection@{smtp_test_server}:11025/?to=fff@home.com'

    #####################
    # Set this up for when we remove the notification from the watch, it should fallback with these details
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-notification_urls": notification_url,
              "application-notification_title": "fallback-title {{watch_title}}  {{ diff_added.splitlines()[0] if diff_added else 'diff added didnt split' }}  " + default_notification_title,
              "application-notification_body": f"some text\n" + default_notification_body + f"\nMore output test\n{ALL_MARKUP_TOKENS}",
              "application-notification_format": 'text',
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

    set_longer_modified_response(datastore_path=datastore_path)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    time.sleep(3)

    msg_raw = get_last_message_from_smtp_server()
    assert len(msg_raw) >= 1
    #time.sleep(60)
    # Parse the email properly using Python's email library
    msg = message_from_string(msg_raw, policy=email_policy)
    # Subject/title got marked up
    subject = msg['subject']
    # Subject should always be plaintext and never marked up to anything else
    assert REMOVED_PLACEMARKER_OPEN not in subject
    assert CHANGED_PLACEMARKER_OPEN not in subject
    assert ADDED_PLACEMARKER_OPEN not in subject
    assert 'diff added didnt split' not in subject
    assert '(changed) Which is across' in subject

    # The email should be plain text only (not multipart)
    assert not msg.is_multipart()
    assert msg.get_content_type() == 'text/plain'

    # Get the plain text content
    text_content = msg.get_content()
    assert '(added) So let\'s see what happens.\r\n' in text_content  # The plaintext part

    # Should NOT contain HTML
    assert '<br>' not in text_content  # We should not have HTML in plain text
    delete_all_watches(client)



def test_check_notification_html_color_format(client, live_server, measure_memory_usage, datastore_path):
    set_original_response(datastore_path=datastore_path)


    notification_url = f'mailto://changedetection@{smtp_test_server}:11025/?to=fff@home.com'

    #####################
    # Set this up for when we remove the notification from the watch, it should fallback with these details
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-notification_urls": notification_url,
              "application-notification_title": "fallback-title {{watch_title}} - diff_added_lines_test : '{{ diff_added.splitlines()[0] if diff_added else 'diff added didnt split' }}' " + default_notification_title,
              "application-notification_body": f"some text\n{default_notification_body}\nMore output test\n{ALL_MARKUP_TOKENS}",
              "application-notification_format": 'htmlcolor',
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
    set_longer_modified_response(datastore_path=datastore_path)
    time.sleep(2)

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    time.sleep(3)

    msg_raw = get_last_message_from_smtp_server()
    assert len(msg_raw) >= 1

    # Parse the email properly using Python's email library
    msg = message_from_string(msg_raw, policy=email_policy)
    # Subject/title got marked up
    subject = msg['subject']
    # Subject should always be plaintext and never marked up to anything else
    assert REMOVED_PLACEMARKER_OPEN not in subject
    assert CHANGED_PLACEMARKER_OPEN not in subject
    assert ADDED_PLACEMARKER_OPEN not in subject
    assert 'diff added didnt split' not in subject
    assert '(changed) Which is across' in subject
    assert 'head title' in subject
    assert "span" not in subject
    assert 'background-color' not in subject


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
    assert HTML_CHANGED_STYLE or HTML_REMOVED_STYLE in html_content
    assert HTML_ADDED_STYLE in html_content
    assert '&lt;' not in html_content

    assert 'some text<br>' in html_content
    delete_all_watches(client)

def test_check_notification_markdown_format(client, live_server, measure_memory_usage, datastore_path):
    set_original_response(datastore_path=datastore_path)


    notification_url = f'mailto://changedetection@{smtp_test_server}:11025/?to=fff@home.com'

    #####################
    # Set this up for when we remove the notification from the watch, it should fallback with these details
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-notification_urls": notification_url,
              "application-notification_title": "fallback-title  diff_added_lines_test : '{{ diff_added.splitlines()[0] if diff_added else 'diff added didnt split' }}' " + default_notification_title,
              "application-notification_body": "*header*\n\nsome text\n" + default_notification_body,
              "application-notification_format": 'markdown',
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
    set_longer_modified_response(datastore_path=datastore_path)
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
    subject = msg['subject']
    # Subject should always be plaintext and never marked up to anything else
    assert REMOVED_PLACEMARKER_OPEN not in subject
    assert CHANGED_PLACEMARKER_OPEN not in subject
    assert ADDED_PLACEMARKER_OPEN not in subject
    assert 'diff added didnt split' not in subject
    assert '(changed) Which is across' in subject


    # Get the parts
    parts = list(msg.iter_parts())
    assert len(parts) == 2

    # First part should be text/plain (the auto-generated plaintext version)
    text_part = parts[0]
    assert text_part.get_content_type() == 'text/plain'
    text_content = text_part.get_content()
    # We wont see anything in the "FALLBACK" text but that's OK (no added/strikethrough etc)
    assert 'So let\'s see what happens.\r\n' in text_content  # The plaintext part


    # Second part should be text/html and roughly converted from markdown to HTML
    html_part = parts[1]
    assert html_part.get_content_type() == 'text/html'
    html_content = html_part.get_content()
    assert '<p><em>header</em></p>' in html_content
    assert '<strong>So let\'s see what happens.</strong><br />' in html_content # Additions are <strong> in markdown
    # the '<br />' will come from apprises conversion, not from our code, we would rather use '<br>' correctly
    # the '<br />' is actually a nice way to know if apprise done the conversion.

    delete_all_watches(client)

# Custom notification body with HTML, that is either sent as HTML or rendered to plaintext and sent
def test_check_notification_email_formats_default_Text_override_HTML(client, live_server, measure_memory_usage, datastore_path):

    # HTML problems? see this
    # https://github.com/caronc/apprise/issues/633

    set_original_response(datastore_path=datastore_path)

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
              "application-notification_format": 'text',
              "requests-time_between_check-minutes": 180,
              'application-fetch_backend': "html_requests"},
        follow_redirects=True
    )
    assert b"Settings updated." in res.data

    # Add a watch and trigger a HTTP POST
    test_url = url_for('test_endpoint',content_type="text/html", _external=True)
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": 'nice one'},
        follow_redirects=True
    )

    assert b"Watch added" in res.data

    #################################### FIRST SITUATION, PLAIN TEXT NOTIFICATION IS WANTED BUT WE HAVE HTML IN OUR TEMPLATE AND CONTENT ##########
    wait_for_all_checks(client)
    set_longer_modified_response(datastore_path=datastore_path)
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
    assert '<!DOCTYPE html>' in text_content # even tho they added html, they selected plaintext so it should have not got converted


    #################################### SECOND SITUATION, HTML IS CORRECTLY PASSED THROUGH TO THE EMAIL ####################
    set_original_response(datastore_path=datastore_path)

    # Now override as HTML format
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "url": test_url,
            "notification_format": 'html',
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
    assert '(removed) So let\'s see what happens.' in html_content  # the html part
    assert '&lt;!DOCTYPE html' not in html_content
    assert '<!DOCTYPE html' in html_content # Our original template is working correctly

    # https://github.com/dgtlmoon/changedetection.io/issues/2103
    assert '<h1>Test</h1>' in html_content
    assert '&lt;' not in html_content

    delete_all_watches(client)

def test_check_plaintext_document_plaintext_notification_smtp(client, live_server, measure_memory_usage, datastore_path):
    """When following a plaintext document, notification in Plain Text format is sent correctly"""
    import os

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write("Some nice plain text\nwhich we add some extra data\nover here\n")

    notification_url = f'mailto://changedetection@{smtp_test_server}:11025/?to=fff@home.com'
    notification_body = f"""{default_notification_body}"""

    #####################
    # Set this up for when we remove the notification from the watch, it should fallback with these details
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-notification_urls": notification_url,
              "application-notification_title": "fallback-title " + default_notification_title,
              "application-notification_body": f"{notification_body}\nMore output test\n{ALL_MARKUP_TOKENS}",
              "application-notification_format": 'text',
              "requests-time_between_check-minutes": 180,
              'application-fetch_backend': "html_requests"},
        follow_redirects=True
    )
    assert b"Settings updated." in res.data

    # Add our URL to the import page
    test_url = url_for('test_endpoint', content_type="text/plain", _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Change the content
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write("Some nice plain text\nwhich we add some extra data\nAnd let's talk about <title> tags\nover here\n")


    time.sleep(1)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Parse the email properly using Python's email library
    msg = message_from_string(get_last_message_from_smtp_server(), policy=email_policy)

    assert not msg.is_multipart()
    assert msg.get_content_type() == 'text/plain'
    body = msg.get_content()
    # nothing is escaped, raw html stuff in text/plain
    assert 'talk about <title> tags' in body
    assert '(added)' in body
    assert '<br' not in body
    assert '&lt;' not in body
    assert '<pre' not in body
    delete_all_watches(client)

def test_check_plaintext_document_html_notifications(client, live_server, measure_memory_usage, datastore_path):
    """When following a plaintext document, notification in Plain Text format is sent correctly"""
    import os

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write("    Some nice plain text\nwhich we add some extra data\nover here\n")

    notification_url = f'mailto://changedetection@{smtp_test_server}:11025/?to=fff@home.com'
    notification_body = f"""{default_notification_body}"""

    #####################
    # Set this up for when we remove the notification from the watch, it should fallback with these details
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-notification_urls": notification_url,
              "application-notification_title": "fallback-title " + default_notification_title,
              "application-notification_body": f"{notification_body}\nMore output test\n{ALL_MARKUP_TOKENS}",
              "application-notification_format": 'html',
              "requests-time_between_check-minutes": 180,
              'application-fetch_backend': "html_requests"},
        follow_redirects=True
    )
    assert b"Settings updated." in res.data

    # Add our URL to the import page
    test_url = url_for('test_endpoint', content_type="text/plain", _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Change the content
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write("    Some nice plain text\nwhich we add some extra data\nAnd let's talk about <title> tags\nover here\n")


    time.sleep(2)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Parse the email properly using Python's email library
    msg = message_from_string(get_last_message_from_smtp_server(), policy=email_policy)


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
    html_part = parts[1]
    assert html_part.get_content_type() == 'text/html'
    html_content = html_part.get_content()


    assert 'And let\'s talk about <title> tags\r\n' in text_content
    assert '&lt;br' not in text_content
    assert '<span' not in text_content


    assert 'talk about <title>' not in html_content  # the html part, should have got marked up to &lt; etc
    assert 'talk about &lt;title&gt;' in html_content
    # Should be the HTML, but not HTML Color
    assert 'background-color' not in html_content
    assert '<br>(added) And let&#39;s talk about &lt;title&gt; tags<br>' in html_content
    assert '&lt;br' not in html_content
    assert '<pre role="article"' in html_content # Should have got wrapped nicely in email_helpers.py

    # And now for the whitespace retention
    assert '&nbsp;&nbsp;&nbsp;&nbsp;Some nice plain text' in html_content
    assert '(added) And let' in html_content # just to show a single whitespace didnt get touched
    delete_all_watches(client)


def test_check_plaintext_document_html_color_notifications(client, live_server, measure_memory_usage, datastore_path):
    """When following a plaintext document, notification in Plain Text format is sent correctly"""
    import os

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write("Some nice plain text\nwhich we add some extra data\nover here\n")

    notification_url = f'mailto://changedetection@{smtp_test_server}:11025/?to=fff@home.com'
    notification_body = f"""{default_notification_body}"""

    #####################
    # Set this up for when we remove the notification from the watch, it should fallback with these details
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-notification_urls": notification_url,
              "application-notification_title": "fallback-title " + default_notification_title,
              "application-notification_body": f"{notification_body}\nMore output test\n{ALL_MARKUP_TOKENS}",
              "application-notification_format": 'htmlcolor',
              "requests-time_between_check-minutes": 180,
              'application-fetch_backend': "html_requests"},
        follow_redirects=True
    )

    assert b"Settings updated." in res.data

    # Add our URL to the import page
    test_url = url_for('test_endpoint', content_type="text/plain", _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Change the content
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write("Some nice plain text\nwhich we add some extra data\nAnd let's talk about <title> tags\nover here\n")

    time.sleep(1)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Parse the email properly using Python's email library
    msg = message_from_string(get_last_message_from_smtp_server(), policy=email_policy)

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
    html_part = parts[1]
    assert html_part.get_content_type() == 'text/html'
    html_content = html_part.get_content()


    assert 'And let\'s talk about <title> tags\r\n' in text_content
    assert '&lt;br' not in text_content
    assert '<span' not in text_content

    assert 'talk about <title>' not in html_content  # the html part, should have got marked up to &lt; etc
    assert 'talk about &lt;title&gt;' in html_content
    # Should be the HTML, but not HTML Color
    assert 'background-color' in html_content
    assert '(added) And let' not in html_content
    assert '&lt;br' not in html_content
    assert '<br>' in html_content
    assert '<pre role="article"' in html_content # Should have got wrapped nicely in email_helpers.py
    delete_all_watches(client)

def test_check_html_document_plaintext_notification(client, live_server, measure_memory_usage, datastore_path):
    """When following a HTML document, notification in Plain Text format is sent correctly"""
    import os

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write("<html><body>some stuff<br>and more stuff<br>and even more stuff<br></body></html>")

    notification_url = f'mailto://changedetection@{smtp_test_server}:11025/?to=fff@home.com'
    notification_body = f"""{default_notification_body}"""

    #####################
    # Set this up for when we remove the notification from the watch, it should fallback with these details
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-notification_urls": notification_url,
              "application-notification_title": "fallback-title " + default_notification_title,
              "application-notification_body": f"{notification_body}\nMore output test\n{ALL_MARKUP_TOKENS}",
              "application-notification_format": 'text',
              "requests-time_between_check-minutes": 180,
              'application-fetch_backend': "html_requests"},
        follow_redirects=True
    )

    assert b"Settings updated." in res.data

    # Add our URL to the import page
    test_url = url_for('test_endpoint', content_type="text/html", _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write("<html><body>sxome stuff<br>and more stuff<br>lets slip this in<br>and this in<br>and even more stuff<br>&lt;tag&gt;</body></html>")

    time.sleep(0.1)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)


    # Parse the email properly using Python's email library
    msg = message_from_string(get_last_message_from_smtp_server(), policy=email_policy)

    assert not msg.is_multipart()
    assert msg.get_content_type() == 'text/plain'
    body = msg.get_content()

    assert '<tag>' in body # Should have got converted from original HTML to plaintext
    assert '(changed) some stuff\r\n' in body
    assert '(into) sxome stuff\r\n' in body
    assert '(added) lets slip this in\r\n' in body
    assert '(added) and this in\r\n' in body
    assert '&nbsp;' not in body


    delete_all_watches(client)


def test_check_html_notification_with_apprise_format_is_html(client, live_server, measure_memory_usage, datastore_path):
    ##  live_server_setup(live_server) # Setup on conftest per function
    set_original_response(datastore_path=datastore_path)


    notification_url = f'mailto://changedetection@{smtp_test_server}:11025/?to=fff@home.com&format=html'

    #####################
    # Set this up for when we remove the notification from the watch, it should fallback with these details
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-notification_urls": notification_url,
              "application-notification_title": "fallback-title " + default_notification_title,
              "application-notification_body": "some text\nfallback-body<br> " + default_notification_body,
              "application-notification_format": 'html',
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
    set_longer_modified_response(datastore_path=datastore_path)
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