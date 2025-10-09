#!/usr/bin/env python3

import time
from flask import url_for
from .util import live_server_setup, wait_for_all_checks
from changedetectionio import html_tools
from . util import  extract_UUID_from_client

def set_original_ignore_response():
    test_return_data = """<html>
       <body>
     Some initial text<br>
     <p>Which is across multiple lines</p>
     <br>
     So let's see what happens.  <br>
     <p>oh yeah 456</p>
     </body>
     </html>

    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)


def test_ignore(client, live_server, measure_memory_usage):
   #  live_server_setup(live_server) # Setup on conftest per function
    set_original_ignore_response()
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    wait_for_all_checks(client)
    uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))
    # use the highlighter endpoint
    res = client.post(
        url_for("ui.ui_edit.highlight_submit_ignore_url", uuid=uuid),
        data={"mode": 'digit-regex', 'selection': 'oh yeah 123'},
        follow_redirects=True
    )

    res = client.get(url_for("ui.ui_edit.edit_page", uuid=uuid))
    # should be a regex now
    assert b'/oh\ yeah\ \d+/' in res.data

    # Should return a link
    assert b'href' in res.data

    # It should not be in the preview anymore
    res = client.get(url_for("ui.ui_views.preview_page", uuid=uuid))
    assert b'<div class="ignored">oh yeah 456' not in res.data

    # Should be in base.html
    assert b'csrftoken' in res.data


def test_strip_ignore_lines(client, live_server, measure_memory_usage):
   #  live_server_setup(live_server) # Setup on conftest per function
    set_original_ignore_response()


    # Goto the settings page, add our ignore text
    res = client.post(
        url_for("settings.settings_page"),
        data={
            "requests-time_between_check-minutes": 180,
            "application-ignore_whitespace": "y",
            "application-strip_ignored_lines": "y",
            "application-global_ignore_text": "Which is across multiple",
            'application-fetch_backend': "html_requests"
        },
        follow_redirects=True
    )
    assert b"Settings updated." in res.data

    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    wait_for_all_checks(client)
    uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))

    # It should not be in the preview anymore
    res = client.get(url_for("ui.ui_views.preview_page", uuid=uuid))
    assert b'<div class="ignored">' not in res.data
    assert b'Which is across multiple' not in res.data
