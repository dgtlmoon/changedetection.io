"""
Regression for #4619.

Markdown to HTML was converted once, then the shared output format was
rewritten to html. A later URL skipped conversion, and a single
apprise.notify() after the loop delivered that last body to every URL.
Mail wrapping also followed the last URL, so an email could be sent as
raw Markdown.
"""

import json
import os
import socketserver
import threading
from email import message_from_bytes
from email.policy import default as email_policy

import pytest

from changedetectionio.notification.handler import process_notification
from changedetectionio.notification_service import NotificationContextData

MARKDOWN_BODY = "**bold change**\n\nsecond line"
CONVERTED_HTML = "<p><strong>bold change</strong></p>"


class _SMTPCapture(socketserver.StreamRequestHandler):
    """Minimal SMTP sink. Records each DATA payload."""

    def handle(self):
        self.wfile.write(b"220 localhost ESMTP\r\n")
        self.wfile.flush()
        collecting = False
        data = []
        while True:
            line = self.rfile.readline()
            if not line:
                break
            if collecting:
                if line in (b".\r\n", b".\n"):
                    self.server.messages.append(b"".join(data))
                    data = []
                    collecting = False
                    self.wfile.write(b"250 OK\r\n")
                    self.wfile.flush()
                else:
                    # Undo SMTP dot-stuffing.
                    if line.startswith(b".."):
                        line = line[1:]
                    data.append(line)
                continue

            command = line.strip().upper()
            if command.startswith((b"EHLO", b"HELO")):
                self.wfile.write(b"250 localhost\r\n")
            elif command == b"DATA":
                collecting = True
                self.wfile.write(b"354 End data with <CR><LF>.<CR><LF>\r\n")
            elif command == b"QUIT":
                self.wfile.write(b"221 Bye\r\n")
                self.wfile.flush()
                break
            else:
                self.wfile.write(b"250 OK\r\n")
            self.wfile.flush()


def _start_smtp_server():
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _SMTPCapture)
    server.messages = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _html_part(raw_message):
    message = message_from_bytes(raw_message, policy=email_policy)
    for part in message.walk():
        if part.get_content_type() == "text/html":
            return part.get_content()
    return ""


@pytest.mark.parametrize("mail_first", [True, False])
def test_markdown_to_html_is_applied_per_notification_url(mail_first, live_server, datastore_path):
    """Each URL gets its own Markdown-to-HTML body. Only the mail URL is wrapped."""
    smtp = _start_smtp_server()
    try:
        smtp_port = smtp.server_address[1]
        mail_url = f"mailto://127.0.0.1:{smtp_port}/?to=someone@example.com&from=alerts@example.com"
        # live_server.url() is the address the fixture actually bound.
        # url_for(_external=True) uses SERVER_NAME (localhost.localdomain), which
        # this environment does not resolve.
        json_url = live_server.url("/test_notification_endpoint?status_code=204").replace(
            "http://", "json://", 1
        )

        urls = [mail_url, json_url] if mail_first else [json_url, mail_url]
        n_object = NotificationContextData(
            initial_data={
                "notification_urls": urls,
                "notification_title": "Markdown notice",
                "notification_body": MARKDOWN_BODY,
                "notification_format": "markdown",
                "watch_url": "https://example.com/watched",
            }
        )

        sent = process_notification(n_object, live_server.app.config["DATASTORE"])

        notification_path = os.path.join(datastore_path, "notification.txt")
        assert os.path.isfile(notification_path), (
            "json:// notification did not reach the test endpoint"
        )
        with open(notification_path) as handle:
            posted = json.loads(handle.read())
        json_message = posted["message"]

        assert smtp.messages, "mailto notification was not delivered"
        email_html = _html_part(smtp.messages[-1])

        # Both services receive converted HTML, not the original Markdown.
        assert CONVERTED_HTML in json_message
        assert "**bold change**" not in json_message
        assert CONVERTED_HTML in email_html
        assert "**bold change**" not in email_html

        # The monospaced email document is only for mail URLs.
        assert "<!DOCTYPE html>" in email_html
        assert "<pre" in email_html
        assert "<!DOCTYPE html>" not in json_message

        assert len(sent) == 2
        by_scheme = {entry["url"].split("://", 1)[0]: entry for entry in sent}
        assert CONVERTED_HTML in by_scheme["mailto"]["body"]
        assert CONVERTED_HTML in by_scheme["json"]["body"]
        # Logged body stays the converted HTML. The email wrapper is applied
        # only to the bytes handed to Apprise for mail URLs.
        assert "<!DOCTYPE html>" not in by_scheme["mailto"]["body"]
        assert "<!DOCTYPE html>" not in by_scheme["json"]["body"]
        assert "original_context" in by_scheme["mailto"]
        assert by_scheme["mailto"]["title"] == "Markdown notice"
        assert by_scheme["json"]["title"] == "Markdown notice"
    finally:
        smtp.shutdown()
        smtp.server_close()
