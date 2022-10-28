#!/usr/bin/python3
# @NOTE:  THIS RELIES ON SOME MIDDLEWARE TO MAKE CHECKBOXES WORK WITH WTFORMS UNDER TEST CONDITION, see changedetectionio/tests/util.py
import time
from flask import url_for
from .util import live_server_setup

def set_original_response():
    test_return_data = """
        Here
        is
        some
        text
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)

def set_response_with_deleted_word():
    test_return_data = """
        Here
        is
        text
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)

def set_response_with_changed_word():
    test_return_data = """
        Here
        ix
        some
        text
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)

def test_diff_filter_changes_as_add_delete(client, live_server):
    live_server_setup(live_server)

    sleep_time_for_fetch_thread = 3

    set_original_response()
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
    # Wait for it to read the original version
    time.sleep(sleep_time_for_fetch_thread)

    #  Make a change that ONLY includes deletes
    set_response_with_deleted_word()
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"trigger_add": "y",
              "trigger_del": "n",
              "url": test_url,
              "fetch_backend": "html_requests"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    time.sleep(sleep_time_for_fetch_thread)

    # We should NOT see a change because we chose to not know about any Deletions
    res = client.get(url_for("index"))
    assert b'unviewed' not in res.data
    # Recheck to be sure
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    time.sleep(sleep_time_for_fetch_thread)
    res = client.get(url_for("index"))
    assert b'unviewed' not in res.data


    # Now set the original response, which will include the word, which should trigger Added (because trigger_add ==y)
    set_original_response()
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    time.sleep(sleep_time_for_fetch_thread)
    res = client.get(url_for("index"))
    assert b'unviewed' in res.data

    # Now check 'changes' are always going to be triggered
    set_original_response()
    client.post(
        url_for("edit_page", uuid="first"),
        # Neither trigger add nor del? then we should see changes still
        data={"trigger_add": "n",
              "trigger_del": "n",
              "url": test_url,
              "fetch_backend": "html_requests"},
        follow_redirects=True
    )
    time.sleep(sleep_time_for_fetch_thread)
    client.get(url_for("mark_all_viewed"), follow_redirects=True)
    set_response_with_changed_word()
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    time.sleep(sleep_time_for_fetch_thread)
    res = client.get(url_for("index"))
    assert b'unviewed' in res.data
