#!/usr/bin/env python3

import time
from flask import url_for
from urllib.request import urlopen
from .util import set_original_response, set_modified_response, live_server_setup, wait_for_all_checks

sleep_time_for_fetch_thread = 3

def test_setup(live_server):
    live_server_setup(live_server)

def test_check_basic_change_detection_functionality_source(client, live_server, measure_memory_usage):
    set_original_response()
    test_url = 'source:'+url_for('test_endpoint', _external=True)
    # Add our URL to the import page
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data

    time.sleep(sleep_time_for_fetch_thread)

    #####################

    # Check HTML conversion detected and workd
    res = client.get(
        url_for("preview_page", uuid="first"),
        follow_redirects=True
    )

    # Check this class DOES appear (that we didnt see the actual source)
    assert b'foobar-detection' in res.data

    # Make a change
    set_modified_response()

    # Force recheck
    res = client.get(url_for("form_watch_checknow"), follow_redirects=True)
    assert b'1 watches queued for rechecking.' in res.data

    wait_for_all_checks(client)

    # Now something should be ready, indicated by having a 'unviewed' class
    res = client.get(url_for("index"))
    assert b'unviewed' in res.data

    res = client.get(
        url_for("diff_history_page", uuid="first"),
        follow_redirects=True
    )

    assert b'&lt;title&gt;modified head title' in res.data



# `subtractive_selectors` should still work in `source:` type requests
def test_check_ignore_elements(client, live_server, measure_memory_usage):
    set_original_response()
    time.sleep(1)
    test_url = 'source:'+url_for('test_endpoint', _external=True)
    # Add our URL to the import page
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data

    wait_for_all_checks(client)

    #####################
    # We want <span> and <p> ONLY, but ignore span with .foobar-detection

    client.post(
        url_for("edit_page", uuid="first"),
        data={"include_filters": 'span,p', "url": test_url, "tags": "", "subtractive_selectors": ".foobar-detection", 'fetch_backend': "html_requests"},
        follow_redirects=True
    )

    time.sleep(sleep_time_for_fetch_thread)

    res = client.get(
        url_for("preview_page", uuid="first"),
        follow_redirects=True
    )
    assert b'foobar-detection' not in res.data
    assert b'&lt;br' not in res.data
    assert b'&lt;p' in res.data
