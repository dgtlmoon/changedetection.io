#!/usr/bin/env python3

from flask import url_for
from changedetectionio.tests.util import live_server_setup, wait_for_all_checks, extract_UUID_from_client, delete_all_watches
import os


def set_response(datastore_path):

    data = """<html>
       <body>Awesome, you made it<br>
yeah the socks request worked<br>
something to ignore<br>
something to trigger<br>
     </body>
     </html>
    """

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(data)

def test_content_filter_live_preview(client, live_server, measure_memory_usage, datastore_path):
   #  live_server_setup(live_server) # Setup on conftest per function
    set_response(datastore_path=datastore_path)
    import time
    test_url = url_for('test_endpoint', _external=True)


    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    time.sleep(0.5)
    wait_for_all_checks(client)

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid),
        data={
            "include_filters": "",
            "fetch_backend": 'html_requests',
            "ignore_text": "something to ignore",
            "trigger_text": "something to trigger",
            "url": test_url,
            "time_between_check_use_default": "y",
        },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    wait_for_all_checks(client)

    # The endpoint is a POST and accepts the form values to override the watch preview
    import json

    # DEFAULT OUTPUT WITHOUT ANYTHING UPDATED/CHANGED - SHOULD SEE THE WATCH DEFAULTS
    res = client.post(
        url_for("ui.ui_edit.watch_get_preview_rendered", uuid=uuid)
    )
    default_return = json.loads(res.data.decode('utf-8'))
    assert default_return.get('after_filter')
    assert default_return.get('before_filter')
    assert default_return.get('ignore_line_numbers') == [3] # "something to ignore" line 3
    assert default_return.get('trigger_line_numbers') == [4] # "something to trigger" line 4

    # SEND AN UPDATE AND WE SHOULD SEE THE OUTPUT CHANGE SO WE KNOW TO HIGHLIGHT NEW STUFF
    res = client.post(
        url_for("ui.ui_edit.watch_get_preview_rendered", uuid=uuid),
        data={
            "include_filters": "",
            "fetch_backend": 'html_requests',
            "ignore_text": "sOckS", # Also be sure case insensitive works
            "trigger_text": "AweSOme",
            "url": test_url,
        },
    )
    reply = json.loads(res.data.decode('utf-8'))
    assert reply.get('after_filter')
    assert reply.get('before_filter')
    assert reply.get('ignore_line_numbers') == [2]  # Ignored - "socks" on line 2
    assert reply.get('trigger_line_numbers') == [1]  # Triggers "Awesome" in line 1

    delete_all_watches(client)


def _setup_version_list_preview(datastore_path, client):
    """Shared HTML fixture for #4138 preview regressions (version tag list)."""
    import time

    data = """<html><body>
0.55.5<br>
0.55.4<br>
0.55.3<br>
0.54.10<br>
0.54.9<br>
</body></html>"""
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(data)

    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    time.sleep(0.5)
    wait_for_all_checks(client)
    return test_url, uuid


def test_preview_ignore_highlight_with_extract_text(client, live_server, measure_memory_usage, datastore_path):
    """Regression for #4138 follow-up: when extract_text rewrites a line (e.g. "0.54.10" → ".54.10"),
    the preview must still highlight that row as 'ignored' even though substring matching against the
    post-extract text fails."""
    import json

    test_url, uuid = _setup_version_list_preview(datastore_path, client)

    res = client.post(
        url_for("ui.ui_edit.watch_get_preview_rendered", uuid=uuid),
        data={
            "include_filters": "",
            "fetch_backend": 'html_requests',
            "ignore_text": "0.54.10",
            "extract_text": r"/(.\d+\.\d+)/",
            "url": test_url,
        },
    )
    reply = json.loads(res.data.decode('utf-8'))
    # The regex strips the leading "0", so the post-extract line for the ignored input is ".54.10".
    # The preview should still mark its position (line 4) as ignored.
    assert reply.get('ignore_line_numbers') == [4], \
        f"Expected line 4 to be highlighted as ignored, got {reply.get('ignore_line_numbers')!r}"

    delete_all_watches(client)


def test_preview_strip_ignored_lines_with_extract_text(client, live_server, measure_memory_usage, datastore_path):
    """Regression for #4138 follow-up: with strip_ignored_lines enabled, an ignored line must be
    removed from the preview output even when extract_text would otherwise rewrite it (0.54.10 → .54.10)."""
    import json

    test_url, uuid = _setup_version_list_preview(datastore_path, client)

    res = client.post(
        url_for("ui.ui_edit.watch_get_preview_rendered", uuid=uuid),
        data={
            "include_filters": "",
            "fetch_backend": 'html_requests',
            "ignore_text": "0.54.10",
            "extract_text": r"/(.\d+\.\d+)/",
            "strip_ignored_lines": "true",
            "url": test_url,
        },
    )
    reply = json.loads(res.data.decode('utf-8'))
    after_filter = reply.get('after_filter', '')

    assert '.54.10' not in after_filter, \
        f"Stripped ignored line should not appear in preview output, got:\n{after_filter!r}"
    assert '0.54.10' not in after_filter
    assert reply.get('ignore_line_numbers') == [], \
        f"Stripped lines need no highlight, got {reply.get('ignore_line_numbers')!r}"

    delete_all_watches(client)
