#!/usr/bin/env python3

import time
from flask import url_for
from .util import live_server_setup, wait_for_all_checks


def set_original_ignore_response():
    test_return_data = """<html>
     <body>
     <p>Some initial text</p>
     <p>Which is across multiple lines</p>
     <p>So let's see what happens.</p>
     <p>&nbsp;  So let's see what happens.   <br> </p>
     <p>A - sortable line</p> 
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)


# The same but just re-ordered the text
def set_modified_swapped_lines():
    # Re-ordered and with some whitespacing, should get stripped() too.
    test_return_data = """<html>
     <body>
     <p>Some initial text</p>
     <p>   So let's see what happens.</p>
     <p>&nbsp;Which is across multiple lines</p>     
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)

def set_modified_swapped_lines_with_extra_text_for_sorting():
    test_return_data = """<html>
     <body>
     <p>&nbsp;Which is across multiple lines</p>     
     <p>Some initial text</p>
     <p>   So let's see what happens.</p>
     <p>Z last</p>
     <p>0 numerical</p>
     <p>A uppercase</p>
     <p>a lowercase</p>     
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)


def set_modified_with_trigger_text_response():
    test_return_data = """<html>
     <body>
     <p>Some initial text</p>
     <p>So let's see what happens.</p>
     <p>and a new line!</p>
     <p>Which is across multiple lines</p>     
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)

def test_setup(client, live_server, measure_memory_usage):
    live_server_setup(live_server)

def test_unique_lines_functionality(client, live_server, measure_memory_usage):
    #live_server_setup(live_server)


    set_original_ignore_response()

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data
    wait_for_all_checks(client)

    # Add our URL to the import page
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"check_unique_lines": "y",
              "url": test_url,
              "fetch_backend": "html_requests"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    assert b'unviewed' not in res.data

    #  Make a change
    set_modified_swapped_lines()

    # Trigger a check
    client.get(url_for("form_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    wait_for_all_checks(client)

    # It should report nothing found (no new 'unviewed' class)
    res = client.get(url_for("index"))
    assert b'unviewed' not in res.data

    # Now set the content which contains the new text and re-ordered existing text
    set_modified_with_trigger_text_response()
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    res = client.get(url_for("index"))
    assert b'unviewed' in res.data
    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

def test_sort_lines_functionality(client, live_server, measure_memory_usage):
    #live_server_setup(live_server)

    set_modified_swapped_lines_with_extra_text_for_sorting()

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data
    wait_for_all_checks(client)

    # Add our URL to the import page
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"sort_text_alphabetically": "n",
              "url": test_url,
              "fetch_backend": "html_requests"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data


    # Trigger a check
    client.get(url_for("form_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    wait_for_all_checks(client)


    res = client.get(url_for("index"))
    # Should be a change registered
    assert b'unviewed' in res.data

    res = client.get(
        url_for("preview_page", uuid="first"),
        follow_redirects=True
    )

    assert res.data.find(b'0 numerical') < res.data.find(b'Z last')
    assert res.data.find(b'A uppercase') < res.data.find(b'Z last')
    assert res.data.find(b'Some initial text') < res.data.find(b'Which is across multiple lines')
    
    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data


def test_extra_filters(client, live_server, measure_memory_usage):
    #live_server_setup(live_server)

    set_original_ignore_response()

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data
    wait_for_all_checks(client)

    # Add our URL to the import page
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"remove_duplicate_lines": "y",
              "trim_text_whitespace": "y",
              "sort_text_alphabetically": "",  # leave this OFF for testing
              "url": test_url,
              "fetch_backend": "html_requests"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    # Give the thread time to pick it up
    wait_for_all_checks(client)
    # Trigger a check
    client.get(url_for("form_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    wait_for_all_checks(client)

    res = client.get(
        url_for("preview_page", uuid="first")
    )

    assert res.data.count(b"see what happens.") == 1

    # still should remain unsorted ('A - sortable line') stays at the end
    assert res.data.find(b'A - sortable line') > res.data.find(b'Which is across multiple lines')

    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data