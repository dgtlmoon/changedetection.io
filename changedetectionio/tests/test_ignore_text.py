#!/usr/bin/env python3

import time
from flask import url_for
from .util import live_server_setup, wait_for_all_checks
from changedetectionio import html_tools



# Unit test of the stripper
# Always we are dealing in utf-8
def test_strip_text_func():
    test_content = """
    Some content
    is listed here

    but sometimes we want to remove the lines.

    but not always."""

    ignore_lines = ["sometimes"]

    stripped_content = html_tools.strip_ignore_text(test_content, ignore_lines)
    assert "sometimes" not in stripped_content
    assert "Some content" in stripped_content

    # Check that line feeds dont get chewed up when something is found
    test_content = "Some initial text\n\nWhich is across multiple lines\n\nZZZZz\n\n\nSo let's see what happens."
    ignore = ['something irrelevent but just to check', 'XXXXX', 'YYYYY', 'ZZZZZ']

    stripped_content = html_tools.strip_ignore_text(test_content, ignore)
    assert stripped_content == "Some initial text\n\nWhich is across multiple lines\n\n\n\nSo let's see what happens."

def set_original_ignore_response(ver_stamp="123"):
    test_return_data = f"""<html>
       <body>
     Some initial text<br>
     <p>Which is across multiple lines</p>
     <br>
     So let's see what happens.  <br>
     <link href="https://www.somesite/wp-content/themes/cooltheme/style2.css?v={ver_stamp}" rel="stylesheet"/>
     </body>
     </html>

    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)


def set_modified_original_ignore_response(ver_stamp="123"):
    test_return_data = f"""<html>
       <body>
     Some NEW nice initial text<br>
     <p>Which is across multiple lines</p>
     <br>
     So let's see what happens.  <br>
     <link href="https://www.somesite/wp-content/themes/cooltheme/style2.css?v={ver_stamp}" rel="stylesheet"/>
     <p>new ignore stuff</p>
     <p>blah</p>
     </body>
     </html>

    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)


# Is the same but includes ZZZZZ, 'ZZZZZ' is the last line in ignore_text
def set_modified_ignore_response(ver_stamp="123"):
    test_return_data = f"""<html>
       <body>
     Some initial text<br>
     <p>Which is across multiple lines</p>
     <P>ZZZZz</P>
     <br>
     So let's see what happens.  <br>
     <link href="https://www.somesite/wp-content/themes/cooltheme/style2.css?v={ver_stamp}" rel="stylesheet"/>
     </body>
     </html>

    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)


# Ignore text now just removes it entirely, is a LOT more simpler code this way

def test_check_ignore_text_functionality(client, live_server, measure_memory_usage):

    # Use a mix of case in ZzZ to prove it works case-insensitive.
    ignore_text = "XXXXX\r\nYYYYY\r\nzZzZZ\r\nnew ignore stuff"
    set_original_ignore_response()


    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    # Give the thread time to pick it up
    wait_for_all_checks(client)

    # Goto the edit page, add our ignore text
    # Add our URL to the import page
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={"ignore_text": ignore_text, "url": test_url, 'fetch_backend': "html_requests"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    # Check it saved
    res = client.get(
        url_for("ui.ui_edit.edit_page", uuid="first"),
    )
    assert bytes(ignore_text.encode('utf-8')) in res.data

    # Trigger a check
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    wait_for_all_checks(client)

    # It should report nothing found (no new 'unviewed' class)
    res = client.get(url_for("watchlist.index"))
    assert b'unviewed' not in res.data
    assert b'/test-endpoint' in res.data

    #  Make a change
    set_modified_ignore_response()

    # Trigger a check
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    # Give the thread time to pick it up
    wait_for_all_checks(client)

    # It should report nothing found (no new 'unviewed' class)
    res = client.get(url_for("watchlist.index"))
    assert b'unviewed' not in res.data
    assert b'/test-endpoint' in res.data



    # Just to be sure.. set a regular modified change..
    set_modified_original_ignore_response()
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.get(url_for("watchlist.index"))
    assert b'unviewed' in res.data

    res = client.get(url_for("ui.ui_views.preview_page", uuid="first"))

    # SHOULD BE be in the preview, it was added in set_modified_original_ignore_response()
    # and we have "new ignore stuff" in ignore_text
    # it is only ignored, it is not removed (it will be highlighted too)
    assert b'new ignore stuff' in res.data

    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

# When adding some ignore text, it should not trigger a change, even if something else on that line changes
def _run_test_global_ignore(client, as_source=False, extra_ignore=""):
    ignore_text = "XXXXX\r\nYYYYY\r\nZZZZZ\r\n"+extra_ignore

    set_original_ignore_response()

    # Goto the settings page, add our ignore text
    res = client.post(
        url_for("settings.settings_page"),
        data={
            "requests-time_between_check-minutes": 180,
            "application-ignore_whitespace": "y",
            "application-global_ignore_text": ignore_text,
            'application-fetch_backend': "html_requests"
        },
        follow_redirects=True
    )
    assert b"Settings updated." in res.data


    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    if as_source:
        # Switch to source mode so we can test that too!
        test_url = "source:"+test_url

    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    # Give the thread time to pick it up
    wait_for_all_checks(client)

    #Adding some ignore text should not trigger a change
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={"ignore_text": "something irrelevent but just to check", "url": test_url, 'fetch_backend': "html_requests"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    wait_for_all_checks(client)
    # Check it saved
    res = client.get(
        url_for("settings.settings_page"),
    )

    for i in ignore_text.splitlines():
        assert bytes(i.encode('utf-8')) in res.data


    # Trigger a check
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    # It should report nothing found (no new 'unviewed' class), adding random ignore text should not cause a change
    res = client.get(url_for("watchlist.index"))
    assert b'unviewed' not in res.data
    assert b'/test-endpoint' in res.data
#####

    # Make a change which includes the ignore text, it should be ignored and no 'change' triggered
    # It adds text with "ZZZZzzzz" and "ZZZZ" is in the ignore list
    # And tweaks the ver_stamp which should be picked up by global regex ignore
    set_modified_ignore_response(ver_stamp=time.time())

    # Trigger a check
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    # Give the thread time to pick it up
    wait_for_all_checks(client)

    # It should report nothing found (no new 'unviewed' class)
    res = client.get(url_for("watchlist.index"))

    assert b'unviewed' not in res.data
    assert b'/test-endpoint' in res.data

    # Just to be sure.. set a regular modified change that will trigger it
    set_modified_original_ignore_response()
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    res = client.get(url_for("watchlist.index"))
    assert b'unviewed' in res.data

    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

def test_check_global_ignore_text_functionality(client, live_server):
    
    _run_test_global_ignore(client, as_source=False)

def test_check_global_ignore_text_functionality_as_source(client, live_server):
    
    _run_test_global_ignore(client, as_source=True, extra_ignore='/\?v=\d/')
