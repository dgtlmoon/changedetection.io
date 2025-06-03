#!/usr/bin/env python3

import time
from flask import url_for
from .util import set_original_response, set_modified_response, live_server_setup, wait_for_all_checks, extract_rss_token_from_UI, \
    extract_UUID_from_client

sleep_time_for_fetch_thread = 3


# Basic test to check inscriptus is not adding return line chars, basically works etc
def test_inscriptus():
    from inscriptis import get_text
    html_content = "<html><body>test!<br>ok man</body></html>"
    stripped_text_from_html = get_text(html_content)
    assert stripped_text_from_html == 'test!\nok man'


def test_check_basic_change_detection_functionality(client, live_server, measure_memory_usage):
    set_original_response()
   #  live_server_setup(live_server) # Setup on conftest per function

    # Add our URL to the import page
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": url_for('test_endpoint', _external=True)},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data

    wait_for_all_checks(client)

    # Do this a few times.. ensures we dont accidently set the status
    for n in range(3):
        client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

        # Give the thread time to pick it up
        wait_for_all_checks(client)

        # It should report nothing found (no new 'unviewed' class)
        res = client.get(url_for("watchlist.index"))
        assert b'unviewed' not in res.data
        assert b'test-endpoint' in res.data

        # Default no password set, this stuff should be always available.

        assert b"SETTINGS" in res.data
        assert b"BACKUP" in res.data
        assert b"IMPORT" in res.data

    #####################

    # Check HTML conversion detected and workd
    res = client.get(
        url_for("ui.ui_views.preview_page", uuid="first"),
        follow_redirects=True
    )
    # Check this class does not appear (that we didnt see the actual source)
    assert b'foobar-detection' not in res.data

    # Make a change
    set_modified_response()

    # Force recheck
    res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    assert b'Queued 1 watch for rechecking.' in res.data

    wait_for_all_checks(client)

    uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))

    # Check the 'get latest snapshot works'
    res = client.get(url_for("ui.ui_edit.watch_get_latest_html", uuid=uuid))
    assert b'which has this one new line' in res.data

    # Now something should be ready, indicated by having a 'unviewed' class
    res = client.get(url_for("watchlist.index"))
    assert b'unviewed' in res.data

    # #75, and it should be in the RSS feed
    rss_token = extract_rss_token_from_UI(client)
    res = client.get(url_for("rss.feed", token=rss_token, _external=True))
    expected_url = url_for('test_endpoint', _external=True)
    assert b'<rss' in res.data

    # re #16 should have the diff in here too
    assert b'(into) which has this one new line' in res.data
    assert b'CDATA' in res.data

    assert expected_url.encode('utf-8') in res.data

    # Following the 'diff' link, it should no longer display as 'unviewed' even after we recheck it a few times
    res = client.get(url_for("ui.ui_views.diff_history_page", uuid=uuid))
    assert b'selected=""' in res.data, "Confirm diff history page loaded"

    # Check the [preview] pulls the right one
    res = client.get(
        url_for("ui.ui_views.preview_page", uuid="first"),
        follow_redirects=True
    )
    assert b'which has this one new line' in res.data
    assert b'Which is across multiple lines' not in res.data

    wait_for_all_checks(client)

    # Do this a few times.. ensures we dont accidently set the status
    for n in range(2):
        client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

        # Give the thread time to pick it up
        wait_for_all_checks(client)

        # It should report nothing found (no new 'unviewed' class)
        res = client.get(url_for("watchlist.index"))
        assert b'unviewed' not in res.data
        assert b'class="has-unviewed' not in res.data
        assert b'head title' not in res.data  # Should not be present because this is off by default
        assert b'test-endpoint' in res.data

    set_original_response()

    # Enable auto pickup of <title> in settings
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-extract_title_as_title": "1", "requests-time_between_check-minutes": 180,
              'application-fetch_backend': "html_requests"},
        follow_redirects=True
    )

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.get(url_for("watchlist.index"))
    assert b'unviewed' in res.data
    assert b'class="has-unviewed' in res.data

    # It should have picked up the <title>
    assert b'head title' in res.data

    # Be sure the last_viewed is going to be greater than the last snapshot
    time.sleep(1)

    # hit the mark all viewed link
    res = client.get(url_for("ui.mark_all_viewed"), follow_redirects=True)
    time.sleep(0.2)

    assert b'class="has-unviewed' not in res.data
    assert b'unviewed' not in res.data

    # #2458 "clear history" should make the Watch object update its status correctly when the first snapshot lands again
    client.get(url_for("ui.clear_watch_history", uuid=uuid))
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    res = client.get(url_for("watchlist.index"))
    assert b'preview/' in res.data

    #
    # Cleanup everything
    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data
