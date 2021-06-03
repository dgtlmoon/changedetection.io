#!/usr/bin/python3

import time
from flask import url_for
from urllib.request import urlopen
from . util import set_original_response, set_modified_response, live_server_setup

sleep_time_for_fetch_thread = 3




def test_check_basic_change_detection_functionality(client, live_server):
    set_original_response()
    live_server_setup(live_server)

    # Add our URL to the import page
    res = client.post(
        url_for("import_page"),
        data={"urls": url_for('test_endpoint', _external=True)},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    time.sleep(sleep_time_for_fetch_thread)

    # Do this a few times.. ensures we dont accidently set the status
    for n in range(3):
        client.get(url_for("api_watch_checknow"), follow_redirects=True)

        # Give the thread time to pick it up
        time.sleep(sleep_time_for_fetch_thread)

        # It should report nothing found (no new 'unviewed' class)
        res = client.get(url_for("index"))
        assert b'unviewed' not in res.data
        assert b'test-endpoint' in res.data

        # Default no password set, this stuff should be always available.

        assert b"SETTINGS" in res.data
        assert b"BACKUP" in res.data
        assert b"IMPORT" in res.data

    #####################

    # Make a change
    set_modified_response()

    res = urlopen(url_for('test_endpoint', _external=True))
    assert b'which has this one new line' in res.read()

    # Force recheck
    res = client.get(url_for("api_watch_checknow"), follow_redirects=True)
    assert b'1 watches are rechecking.' in res.data

    time.sleep(sleep_time_for_fetch_thread)

    # Now something should be ready, indicated by having a 'unviewed' class
    res = client.get(url_for("index"))
    assert b'unviewed' in res.data

    # #75, and it should be in the RSS feed
    res = client.get(url_for("index", rss="true"))
    expected_url = url_for('test_endpoint', _external=True)
    assert b'<rss' in res.data
    assert expected_url.encode('utf-8') in res.data

    # Following the 'diff' link, it should no longer display as 'unviewed' even after we recheck it a few times
    res = client.get(url_for("diff_history_page", uuid="first"))
    assert b'Compare newest' in res.data

    time.sleep(2)

    # Do this a few times.. ensures we dont accidently set the status
    for n in range(2):
        client.get(url_for("api_watch_checknow"), follow_redirects=True)

        # Give the thread time to pick it up
        time.sleep(sleep_time_for_fetch_thread)

        # It should report nothing found (no new 'unviewed' class)
        res = client.get(url_for("index"))
        assert b'unviewed' not in res.data
        assert b'test-endpoint' in res.data

    set_original_response()

    client.get(url_for("api_watch_checknow"), follow_redirects=True)
    time.sleep(sleep_time_for_fetch_thread)
    res = client.get(url_for("index"))
    assert b'unviewed' in res.data

    # Cleanup everything
    res = client.get(url_for("api_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

