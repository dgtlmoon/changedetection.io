#!/usr/bin/env python3
"""Test suite for the render/not render anchor tag content functionality"""

import time
from flask import url_for
from .util import live_server_setup, wait_for_all_checks




def set_original_ignore_response():
    test_return_data = """<html>
       <body>
     Some initial text<br>
     <a href="/original_link"> Some More Text </a>
     <br>
     So let's see what happens.  <br>
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)


# Should be the same as set_original_ignore_response() but with a different
# link
def set_modified_ignore_response():
    test_return_data = """<html>
       <body>
     Some initial text<br>
     <a href="/modified_link"> Some More Text </a>
     <br>
     So let's see what happens.  <br>
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)

def test_render_anchor_tag_content_true(client, live_server, measure_memory_usage):
    """Testing that the link changes are detected when
    render_anchor_tag_content setting is set to true"""
    sleep_time_for_fetch_thread = 3

    # Give the endpoint time to spin up
    time.sleep(1)

    # set original html text
    set_original_ignore_response()

    # Goto the settings page, choose to ignore links (dont select/send "application-render_anchor_tag_content")
    res = client.post(
        url_for("settings.settings_page"),
        data={
            "requests-time_between_check-minutes": 180,
            "application-fetch_backend": "html_requests",
        },
        follow_redirects=True,
    )
    assert b"Settings updated." in res.data

    # Add our URL to the import page
    test_url = url_for("test_endpoint", _external=True)
    res = client.post(
        url_for("imports.import_page"), data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    wait_for_all_checks(client)
    # Trigger a check
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    # set a new html text with a modified link
    set_modified_ignore_response()
    wait_for_all_checks(client)

    # Trigger a check
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    wait_for_all_checks(client)

    # We should not see the rendered anchor tag
    res = client.get(url_for("ui.ui_views.preview_page", uuid="first"))
    assert '(/modified_link)' not in res.data.decode()

    # Goto the settings page, ENABLE render anchor tag
    res = client.post(
        url_for("settings.settings_page"),
        data={
            "requests-time_between_check-minutes": 180,
            "application-render_anchor_tag_content": "true",
            "application-fetch_backend": "html_requests",
        },
        follow_redirects=True,
    )
    assert b"Settings updated." in res.data

    # Trigger a check
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    wait_for_all_checks(client)



    # check that the anchor tag content is rendered
    res = client.get(url_for("ui.ui_views.preview_page", uuid="first"))
    assert '(/modified_link)' in res.data.decode()

    # since the link has changed, and we chose to render anchor tag content,
    # we should detect a change (new 'unviewed' class)
    res = client.get(url_for("watchlist.index"))
    assert b"unviewed" in res.data
    assert b"/test-endpoint" in res.data

    # Cleanup everything
    res = client.get(url_for("ui.form_delete", uuid="all"),
                     follow_redirects=True)
    assert b'Deleted' in res.data

