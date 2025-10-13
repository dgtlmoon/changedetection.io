#!/usr/bin/env python3

import time
from flask import url_for
from .util import set_original_response, set_modified_response, live_server_setup, wait_for_all_checks, extract_rss_token_from_UI, \
    extract_UUID_from_client, delete_all_watches

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

        # It should report nothing found (no new 'has-unread-changes' class)
        res = client.get(url_for("watchlist.index"))
        assert b'has-unread-changes' not in res.data
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

    # Now something should be ready, indicated by having a 'has-unread-changes' class
    res = client.get(url_for("watchlist.index"))
    assert b'has-unread-changes' in res.data

    # #75, and it should be in the RSS feed
    rss_token = extract_rss_token_from_UI(client)
    res = client.get(url_for("rss.feed", token=rss_token, _external=True))
    expected_url = url_for('test_endpoint', _external=True)
    assert b'<rss' in res.data

    # re #16 should have the diff in here too
    assert b'(into) which has this one new line' in res.data
    assert b'CDATA' in res.data

    assert expected_url.encode('utf-8') in res.data
#
    # Following the 'diff' link, it should no longer display as 'has-unread-changes' even after we recheck it a few times
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


    # Do this a few times.. ensures we don't accidently set the status
    for n in range(2):
        res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
        # Give the thread time to pick it up
        wait_for_all_checks(client)

        # It should report nothing found (no new 'has-unread-changes' class)
        res = client.get(url_for("watchlist.index"))


        assert b'has-unread-changes' not in res.data
        assert b'class="has-unread-changes' not in res.data
        assert b'head title' in res.data  # Should be ON by default
        assert b'test-endpoint' in res.data

    # Recheck it but only with a title change, content wasnt changed
    set_original_response(extra_title=" and more")

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    res = client.get(url_for("watchlist.index"))
    assert b'head title and more' in res.data

    # disable <title> pickup
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-ui-use_page_title_in_list": "", "requests-time_between_check-minutes": 180,
              'application-fetch_backend': "html_requests"},
        follow_redirects=True
    )

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.get(url_for("watchlist.index"))
    assert b'has-unread-changes' in res.data
    assert b'class="has-unread-changes' in res.data
    assert b'head title' not in res.data  # should now be off


    # Be sure the last_viewed is going to be greater than the last snapshot
    time.sleep(1)

    # hit the mark all viewed link
    res = client.get(url_for("ui.mark_all_viewed"), follow_redirects=True)

    assert b'class="has-unread-changes' not in res.data
    assert b'has-unread-changes' not in res.data

    # #2458 "clear history" should make the Watch object update its status correctly when the first snapshot lands again
    client.get(url_for("ui.clear_watch_history", uuid=uuid))
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    res = client.get(url_for("watchlist.index"))
    assert b'preview/' in res.data

    #
    # Cleanup everything
    delete_all_watches(client)


# Server says its plaintext, we should always treat it as plaintext, and then if they have a filter, try to apply that
def test_requests_timeout(client, live_server, measure_memory_usage):
    delay = 2
    test_url = url_for('test_endpoint', delay=delay, _external=True)

    res = client.post(
        url_for("settings.settings_page"),
        data={"application-ui-use_page_title_in_list": "",
              "requests-time_between_check-minutes": 180,
              "requests-timeout": delay - 1,
              'application-fetch_backend': "html_requests"},
        follow_redirects=True
    )

    # Add our URL to the import page
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # requests takes >2 sec but we timeout at 1 second
    res = client.get(url_for("watchlist.index"))
    assert b'Read timed out. (read timeout=1)' in res.data

    ##### Now set a longer timeout
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-ui-use_page_title_in_list": "",
              "requests-time_between_check-minutes": 180,
              "requests-timeout": delay + 1, # timeout should be a second more than the reply time
              'application-fetch_backend': "html_requests"},
        follow_redirects=True
    )
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    wait_for_all_checks(client)

    res = client.get(url_for("watchlist.index"))
    assert b'Read timed out' not in res.data

def test_non_text_mime_or_downloads(client, live_server, measure_memory_usage):
    """

    https://github.com/dgtlmoon/changedetection.io/issues/3434
    I noticed that a watched website can be monitored fine as long as the server sends content-type: text/plain; charset=utf-8,
    but once the server sends content-type: application/octet-stream (which is usually done to force the browser to show the Download dialog),
    changedetection somehow ignores all line breaks and treats the document file as if everything is on one line.

    WHAT THIS DOES - makes the system rely on 'magic' to determine what is it

    :param client:
    :param live_server:
    :param measure_memory_usage:
    :return:
    """
    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write("""some random text that should be split by line
and not parsed with html_to_text
this way we know that it correctly parsed as plain text
\r\n
ok\r\n
got it\r\n
""")

    test_url = url_for('test_endpoint', content_type="application/octet-stream", _external=True)

    # Add our URL to the import page
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    wait_for_all_checks(client)

    ### check the front end
    res = client.get(
        url_for("ui.ui_views.preview_page", uuid="first"),
        follow_redirects=True
    )
    assert b"some random text that should be split by line\n" in res.data
    ####

    # Check the snapshot by API that it has linefeeds too
    watch_uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))
    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')
    res = client.get(
        url_for("watchhistory", uuid=watch_uuid),
        headers={'x-api-key': api_key},
    )

    # Fetch a snapshot by timestamp, check the right one was found
    res = client.get(
        url_for("watchsinglehistory", uuid=watch_uuid, timestamp=list(res.json.keys())[-1]),
        headers={'x-api-key': api_key},
    )
    assert b"some random text that should be split by line\n" in res.data


    delete_all_watches(client)


def test_standard_text_plain(client, live_server, measure_memory_usage):
    """

    https://github.com/dgtlmoon/changedetection.io/issues/3434
    I noticed that a watched website can be monitored fine as long as the server sends content-type: text/plain; charset=utf-8,
    but once the server sends content-type: application/octet-stream (which is usually done to force the browser to show the Download dialog),
    changedetection somehow ignores all line breaks and treats the document file as if everything is on one line.

    The real bug here can be that it will try to process plain-text as HTML, losing <etc>

    :param client:
    :param live_server:
    :param measure_memory_usage:
    :return:
    """
    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write("""some random text that should be split by line
and not parsed with html_to_text
<title>Even this title should stay because we are just plain text</title>
this way we know that it correctly parsed as plain text
\r\n
ok\r\n
got it\r\n
""")

    test_url = url_for('test_endpoint', content_type="text/plain", _external=True)

    # Add our URL to the import page
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    wait_for_all_checks(client)

    ### check the front end
    res = client.get(
        url_for("ui.ui_views.preview_page", uuid="first"),
        follow_redirects=True
    )

    assert b"some random text that should be split by line\n" in res.data
    ####

    # Check the snapshot by API that it has linefeeds too
    watch_uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))
    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')
    res = client.get(
        url_for("watchhistory", uuid=watch_uuid),
        headers={'x-api-key': api_key},
    )

    # Fetch a snapshot by timestamp, check the right one was found
    res = client.get(
        url_for("watchsinglehistory", uuid=watch_uuid, timestamp=list(res.json.keys())[-1]),
        headers={'x-api-key': api_key},
    )
    assert b"some random text that should be split by line\n" in res.data
    assert b"<title>Even this title should stay because we are just plain text</title>" in res.data

    delete_all_watches(client)

# Server says its plaintext, we should always treat it as plaintext
def test_plaintext_even_if_xml_content(client, live_server, measure_memory_usage):

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write("""<?xml version="1.0" encoding="utf-8"?>
<resources xmlns:tools="http://schemas.android.com/tools">
    <!--Activity and fragment titles-->
    <string name="feed_update_receiver_name">Abonnementen bijwerken</string>
</resources>
""")

    test_url = url_for('test_endpoint', content_type="text/plain", _external=True)

    # Add our URL to the import page
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    wait_for_all_checks(client)

    res = client.get(
        url_for("ui.ui_views.preview_page", uuid="first"),
        follow_redirects=True
    )

    assert b'&lt;string name=&#34;feed_update_receiver_name&#34;' in res.data

    delete_all_watches(client)

# Server says its plaintext, we should always treat it as plaintext, and then if they have a filter, try to apply that
def test_plaintext_even_if_xml_content_and_can_apply_filters(client, live_server, measure_memory_usage):


    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write("""<?xml version="1.0" encoding="utf-8"?>
<resources xmlns:tools="http://schemas.android.com/tools">
    <!--Activity and fragment titles-->
    <string name="feed_update_receiver_name">Abonnementen bijwerken</string>
    <foobar>ok man</foobar>
</resources>
""")

    test_url=url_for('test_endpoint', content_type="text/plain", _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url, extras={"include_filters": ['//string']})
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.get(
        url_for("ui.ui_views.preview_page", uuid="first"),
        follow_redirects=True
    )

    assert b'&lt;string name=&#34;feed_update_receiver_name&#34;' in res.data
    assert b'&lt;foobar' not in res.data

    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
