#!/usr/bin/env python3
"""
Reflected XSS regression tests for /diff/<uuid>/download-patch (GHSA-23mp-8222-96fr).

get_history_snapshot() does a plain dict lookup on the history, so an unknown timestamp
raised KeyError whose str() carries the raw from_version/to_version query parameter. The
error path interpolated that into make_response(), which defaults to text/html - so the
parameter was reflected unescaped and executed in the victim's browser.

Two independent guarantees are asserted here, because either alone would have prevented
this bug and both are worth keeping:
  1. Unknown timestamps are rejected up front (404), so the exception never fires.
  2. Whatever the error path returns is text/plain and never echoes the input.

This is the third instance of the same pattern, after CVE-2026-27645 (/rss/watch/) and
CVE-2026-29038 (/rss/tag/).
"""

import os
from flask import url_for
from .util import wait_for_all_checks

XSS_PAYLOADS = [
    '<svg/onload=alert(document.domain)>',
    '"><script>alert(1)</script>',
    "'><img src=x onerror=alert(1)>",
]


def _setup_watch_with_history(client, datastore_path):
    """A watch needs >=2 snapshots before download-patch will get as far as the lookup."""
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write("first content")

    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write("second content, now different")
    client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    return uuid


def test_download_patch_does_not_reflect_unknown_timestamp(client, live_server, measure_memory_usage, datastore_path):
    uuid = _setup_watch_with_history(client, datastore_path)

    for payload in XSS_PAYLOADS:
        # from_version and to_version are separate code paths; both must be validated
        for param in ('from_version', 'to_version'):
            res = client.get(url_for("ui.ui_diff.download_patch", uuid=uuid, **{param: payload}))

            assert payload.encode() not in res.data, \
                f"{param}={payload!r} was reflected into the response body"

            # An unknown timestamp is a client error, not a 500 from an unhandled KeyError
            assert res.status_code == 404, \
                f"{param}={payload!r} should be rejected up front, got {res.status_code}"

            # Even if a future refactor lets the exception path run again, the body must
            # not be parseable as HTML
            if res.status_code >= 400:
                assert 'text/html' not in res.headers.get('Content-Type', ''), \
                    f"error response for {param}={payload!r} should not be text/html"


def test_download_patch_still_works_for_valid_timestamps(client, live_server, measure_memory_usage, datastore_path):
    """The validation must not break the legitimate path."""
    uuid = _setup_watch_with_history(client, datastore_path)
    watch = client.application.config.get('DATASTORE').data['watching'][uuid]
    dates = list(watch.history.keys())
    assert len(dates) >= 2

    res = client.get(url_for("ui.ui_diff.download_patch", uuid=uuid,
                             from_version=dates[-2], to_version=dates[-1]))
    assert res.status_code == 200
    assert 'text/plain' in res.headers.get('Content-Type', '')
    assert b'second content' in res.data, "Patch should contain the changed text"

    # And with no params at all it should default to the last two snapshots
    res = client.get(url_for("ui.ui_diff.download_patch", uuid=uuid))
    assert res.status_code == 200
    assert b'second content' in res.data
