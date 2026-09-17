#!/usr/bin/env python3
"""
Issue #4299: static resources went out with two Date header lines.

werkzeug's send_file() (via make_conditional) puts a Date header on the WSGI
response, and the built-in server we run in production - started through
socketio.run(..., allow_unsafe_werkzeug=True) - writes its own Date in
BaseHTTPRequestHandler.send_response() before copying the app's headers
through verbatim, so the response on the wire carried Date twice. RFC 9110
forbids that and nginx drops the whole field with "upstream sent duplicate
header line".

The duplicate is only visible over a real socket, hence live_server and
http.client here: the Flask test client talks to the WSGI app directly and
never sees the server-added header, and requests/urllib3 would merge the two
header lines into one before we could count them.
"""

import http.client
import re
from urllib.parse import urlparse


def test_no_duplicate_date_header_on_static_resources(live_server):
    # Served by send_from_directory(), which is the path that makes werkzeug
    # attach its own Date - any static file exercises the same code.
    url = urlparse(live_server.url('/static/styles/styles.css'))
    conn = http.client.HTTPConnection(url.hostname, url.port, timeout=10)
    try:
        conn.request('GET', url.path)
        response = conn.getresponse()
        response.read()
        # getheaders() keeps repeated header lines as separate entries
        headers = response.getheaders()
        status = response.status
    finally:
        conn.close()

    assert status == 200, f"expected 200 for the static file, got {status}"

    dates = [value for key, value in headers if key.lower() == 'date']
    assert len(dates) == 1, (
        f"expected exactly 1 Date header, got {len(dates)}: {dates!r} - RFC 9110 forbids a "
        f"duplicated Date, and nginx logs 'upstream sent duplicate header line' and ignores it"
    )
    assert re.match(r'^\w{3}, \d{2} \w{3} \d{4} \d{2}:\d{2}:\d{2} GMT$', dates[0]), (
        f"Date header is not a valid IMF-fixdate: {dates[0]!r}"
    )
