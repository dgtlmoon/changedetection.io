#!/usr/bin/env python3
"""
Issue #4299: Duplicate Date HTTP header for static resources.

Static files are served via werkzeug send_from_directory/send_file, whose
make_conditional() injects a Date header into the WSGI response. When the
app runs on Werkzeug's built-in server (the default dev/LXC/docker-entrypoint
path, started through socketio.run(..., allow_unsafe_werkzeug=True)),
BaseHTTPRequestHandler.send_response() emits its own Date header too — so the
wire response carries two Date header lines, which nginx rejects with
"upstream sent duplicate header line" and which RFC 9110 forbids.

This test hits the live server over real HTTP (the Flask test client talks to
the WSGI app directly and never sees the server-added header), and asserts the
Date header appears exactly once.
"""

import http.client
import re
import socket
import time
from urllib.parse import urlparse


def _get_raw_headers(url):
    """Return the raw response header lines (list of (key, value)) — unlike
    requests/urllib3, these are not merged, so a duplicated header line is
    visible as two entries."""
    parsed = urlparse(url)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=10)
    try:
        conn.request('GET', parsed.path)
        resp = conn.getresponse()
        resp.read()
        return resp.status, resp.getheaders()
    finally:
        conn.close()


def _assert_single_date_header(status, headers, label):
    assert status == 200, f"{label}: expected 200, got {status}"
    dates = [value for key, value in headers if key.lower() == 'date']
    assert len(dates) == 1, (
        f"{label}: expected exactly 1 Date header, got {len(dates)}: {dates!r} "
        f"(RFC 9110 forbids a duplicated Date header; nginx logs "
        f"'upstream sent duplicate header line' and ignores the whole field)"
    )
    assert re.match(r'^\w{3}, \d{2} \w{3} \d{4} \d{2}:\d{2}:\d{2} GMT$', dates[0]), (
        f"{label}: Date header is not a valid IMF-fixdate: {dates[0]!r}"
    )


def test_no_duplicate_date_header_on_static_resources(app, live_server):
    # Wait for the live server socket to accept connections
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            with socket.create_connection((live_server.host, live_server.port), timeout=1):
                break
        except OSError:
            time.sleep(0.2)
    else:
        raise AssertionError("live server did not come up in time")

    # The exact resources named in the issue report
    for group, filename in [('js', 'jquery-3.6.0.min.js'), ('styles', 'styles.css')]:
        url = live_server.url(f"/static/{group}/{filename}")
        status, headers = _get_raw_headers(url)
        _assert_single_date_header(status, headers, f"static/{group}/{filename}")
