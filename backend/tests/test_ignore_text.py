#!/usr/bin/python3

import time
from flask import url_for
from urllib.request import urlopen
import pytest


# Unit test of the stripper
def test_strip_text_func():
    from backend import fetch_site_status

    test_content = """
    Some content
    is listed here

    but sometimes we want to remove the lines.

    but not always."""

    original_length = len(test_content.splitlines())

    fetcher = fetch_site_status.perform_site_check(datastore=False)

    ignore_lines = ["sometimes"]

    stripped_content = fetcher.strip_ignore_text(test_content, ignore_lines)

    # Should be one line shorter
    assert len(stripped_content.splitlines()) == original_length - 1

    assert "sometimes" not in stripped_content
    assert "Some content" in stripped_content


def set_original_ignore_response():
    test_return_data = """<html>
       <body>
     Some initial text</br>
     <p>Which is across multiple lines</p>
     </br>
     So let's see what happens.  </br>
     </body>
     </html>

    """

    with open("test-datastore/output.txt", "w") as f:
        f.write(test_return_data)


# Is the same but includes ZZZZZ, 'ZZZZZ' is the last line in ignore_text
def set_modified_ignore_response():
    test_return_data = """<html>
       <body>
     Some initial text</br>
     <p>Which is across multiple lines</p>
     <P>ZZZZZ</P>
     </br>
     So let's see what happens.  </br>
     </body>
     </html>

    """

    with open("test-datastore/output.txt", "w") as f:
        f.write(test_return_data)


def test_check_ignore_text_functionality(client, live_server):
    sleep_time_for_fetch_thread = 5

    ignore_text = "XXXXX\nYYYYY\nZZZZZ"
    set_original_ignore_response()

    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    # Goto the edit page, add our ignore text
    # Add our URL to the import page
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"ignore-text": ignore_text, "url": test_url, "tag": "", "headers": ""},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    # Check it saved
    res = client.get(
        url_for("edit_page", uuid="first"),
    )
    assert bytes(ignore_text.encode('utf-8')) in res.data

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(sleep_time_for_fetch_thread)

    # It should report nothing found (no new 'unviewed' class)
    res = client.get(url_for("index"))
    assert b'unviewed' not in res.data
    assert b'/test-endpoint' in res.data

    set_modified_ignore_response()

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(sleep_time_for_fetch_thread)

    # It should report nothing found (no new 'unviewed' class)
    res = client.get(url_for("index"))
    assert b'unviewed' not in res.data
    assert b'/test-endpoint' in res.data

    res = client.get(url_for("api_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

