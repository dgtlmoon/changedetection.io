import os
import time
from flask import url_for
from changedetectionio.tests.util import set_original_response, set_modified_response, set_more_modified_response, live_server_setup, \
    wait_for_all_checks, \
    set_longer_modified_response
import logging

# NOTE - RELIES ON mailserver as hostname running, see github build recipes
# Should be hostname (never IP), looks for our test mailserver that repeats the content
# python3 changedetectionio/tests/smtp/smtp-test-server.py &
# mailserver=localhost pytest tests/smtp/test_notification_smtp.py::test_check_notification_email_formats_default_HTML
smtp_test_server = os.getenv('mailserver', 'mailserver')


from changedetectionio.notification import (
    default_notification_body,
    default_notification_format,
    default_notification_title,
    valid_notification_formats,
)

from email import policy
from email.parser import BytesParser, Parser

def parse_mime(raw):
    """Return (EmailMessage, dict[str, list[str]] bodies by content-type)."""
    if isinstance(raw, (bytes, bytearray)):
        msg = BytesParser(policy=policy.default).parsebytes(raw)
    else:
        msg = Parser(policy=policy.default).parsestr(raw)

    parts_by_type = {}
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            ctype = part.get_content_type()           # e.g. "text/plain"
            text = part.get_content()                 # decoded str
            parts_by_type.setdefault(ctype, []).append(text)
    else:
        parts_by_type.setdefault(msg.get_content_type(), []).append(msg.get_content())

    return msg, parts_by_type

def one_or_join(parts_dict, ctype):
    """Join multiple parts of the same type (rare but possible)."""
    return "\n".join(parts_dict.get(ctype, []))

def norm_newlines(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")

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

    raw = get_last_message_from_smtp_server()
    assert raw  # not empty

    msg, bodies = parse_mime(raw)

    plain = norm_newlines(one_or_join(bodies, "text/plain"))
    html = norm_newlines(one_or_join(bodies, "text/html"))

    # Now assert against the decoded bodies
    assert "(added) So let's see what happens.\n" in plain  # plaintext uses a literal apostrophe
    assert "(added) So let&#39;s see what happens.<br>" in html  # html uses &#39; and <br>

    # You can also check counts, boundaries, etc.
    assert html.count("So let&#39;s see what happens.") == 3
    assert "modified head title had a change." in plain
    assert "modified head title had a change.<br>" in html



    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data


def test_check_notification_email_formats_default_Text_override_HTML(client, live_server, measure_memory_usage):

    # HTML problems? see this
    # https://github.com/caronc/apprise/issues/633
    set_original_response()
    notification_url = f'mailto://changedetection@{smtp_test_server}:11025/?to=fff@home.com'
    notification_body = f"""{default_notification_body}"""

    #####################
    # Set this up for when we remove the notification from the watch, it should fallback with these details
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-notification_urls": notification_url,
              "application-notification_title": "fallback-title " + default_notification_title,
              "application-notification_body": notification_body,
              "application-notification_format": 'Text', # handler.py should be sure to add &format=text to override default html from apprise
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
    raw = get_last_message_from_smtp_server()
    assert raw

    msg, bodies = parse_mime(raw)

    plain = norm_newlines(one_or_join(bodies, "text/plain"))
    html = norm_newlines(one_or_join(bodies, "text/html"))
    assert not html # should be no HTML here

    # Expect ONLY text/plain body
    assert "text/plain" in bodies
    assert "text/html" not in bodies

    # Assert on decoded plaintext (literal apostrophe, not &#39;)
    # Should be NO markup when in text mode
    assert "(added) So let's see what happens.\n" in plain


    # ---------- Flip to HTML format, then expect multipart with both ----------
    set_original_response()
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={"url": test_url,
              "notification_format": "HTML",
              "fetch_backend": "html_requests",
              "time_between_check_use_default": "y"},
        follow_redirects=True,
    )

    assert b"Updated watch." in res.data
    wait_for_all_checks(client)

    time.sleep(3)

    raw = get_last_message_from_smtp_server()
    assert raw

    msg, bodies = parse_mime(raw)
    plain = norm_newlines(one_or_join(bodies, "text/plain"))
    html = norm_newlines(one_or_join(bodies, "text/html"))

    # Expect both text/plain and text/html bodies now
    assert "text/plain" in bodies
    assert "text/html" in bodies

    # Plaintext reflects the removal line (literal apostrophe)
    assert "(removed) So let's see what happens.\n" in plain
    assert "(removed) So let&#39;s see what happens.<br>" in html

    # Optional: ensure we got multipart/alternative (typical for dual bodies)
    if msg.is_multipart():
        # most senders do "multipart/alternative" for text/plain + text/html
        assert msg.get_content_subtype() in ("alternative", "mixed", "related")
