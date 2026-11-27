#!/usr/bin/env python3

import os
import re
import time
from flask import url_for
from .util import (
    set_original_response,
    set_modified_response,
    live_server_setup,
    wait_for_all_checks, delete_all_watches
)
from loguru import logger

def run_socketio_watch_update_test(client, live_server, password_mode="", datastore_path=""):
    """Test that the socketio emits a watch update event when content changes"""

    # Set up the test server
    set_original_response(datastore_path=datastore_path)


    # Get the SocketIO instance from the app
    from changedetectionio.flask_app import app
    socketio = app.extensions['socketio']

    # Create a test client for SocketIO
    socketio_test_client = socketio.test_client(app, flask_test_client=client)
    if password_mode == "not logged in, should exit on connect":
        assert not socketio_test_client.is_connected(), "Failed to connect to Socket.IO server because it should bounce this connect"
        return

    assert socketio_test_client.is_connected(), "Failed to connect to Socket.IO server"
    print("Successfully connected to Socket.IO server")

    # Add our URL to the import page
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": url_for('test_endpoint', _external=True)},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    res = client.get(url_for("watchlist.index"))
    assert url_for('test_endpoint', _external=True).encode() in res.data

    # Wait for initial check to complete
    wait_for_all_checks(client)

    # Per-watch events are only sent for the watches a page says it is showing
    socketio_test_client.emit('watch-subscribe', {'uuids': list(live_server.app.config['DATASTORE'].data['watching'].keys())})

    # Clear any initial messages
    socketio_test_client.get_received()

    # Make a change to trigger an update
    set_modified_response(datastore_path=datastore_path)

    # Force recheck
    res = client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
    assert b'Queued 1 watch for rechecking.' in res.data

    # Wait for the watch to be checked
    wait_for_all_checks(client)

    has_watch_update = False
    has_unviewed_update = False
    got_general_stats_update = False

    for i in range(10):
        # Get received events
        received = socketio_test_client.get_received()

        if received:
            logger.info(f"Received {len(received)} events after {i+1} seconds")
            for event in received:
                if event['name'] == 'watch_update':
                    has_watch_update = True
                if event['name'] == 'general_stats_update':
                    got_general_stats_update = True

        if has_unviewed_update:
            break

        # Force a recheck every 5 seconds to ensure events are emitted
#        if i > 0 and i % 5 == 0:
#            print(f"Still waiting for events, forcing another recheck...")
#            res = client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
#            assert b'Queued 1 watch for rechecking.' in res.data
#            wait_for_all_checks(client)

#        print(f"Waiting for unviewed update event... {i+1}/{max_wait}")
        time.sleep(1)

    # Verify we received watch_update events
    assert has_watch_update, "No watch_update events received"

    # Verify we received an unviewed event
    assert got_general_stats_update, "Got general stats update event"

    # Alternatively, check directly if the watch in the datastore is marked as unviewed
    from changedetectionio.flask_app import app
    datastore = app.config.get('DATASTORE')

    watch_uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))

    # Get the watch from the datastore
    watch = datastore.data['watching'].get(watch_uuid)
    assert watch, f"Watch {watch_uuid} not found in datastore"
    assert watch.has_unviewed, "The watch was not marked as unviewed after content change"

    # Clean up
    delete_all_watches(client)

def test_everything(live_server, client, measure_memory_usage, datastore_path):

   #  live_server_setup(live_server) # Setup on conftest per function

    run_socketio_watch_update_test(password_mode="", live_server=live_server, client=client, datastore_path=datastore_path)

    ############################ Password required auth check ##############################

    # Enable password check and diff page access bypass
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-password": "foobar",
              "requests-time_between_check-minutes": 180,
              'application-fetch_backend': "html_requests"},
        follow_redirects=True
    )

    assert b"Password protection enabled." in res.data

    run_socketio_watch_update_test(password_mode="not logged in, should exit on connect", live_server=live_server, client=client, datastore_path=datastore_path)
    res = client.post(
        url_for("login"),
        data={"password": "foobar"},
        follow_redirects=True
    )

    # Yes we are correctly logged in
    assert b"/logout" in res.data
    run_socketio_watch_update_test(password_mode="should be like normal", live_server=live_server, client=client, datastore_path=datastore_path)


# The watch list is kept current with whole rows: every update of a watch sends its row as the list's own template
# draws it ("watch_row"), and the page puts it in place of the one it has.

def _set_restock_product(datastore_path, price, in_stock=True):
    availability = 'InStock' if in_stock else 'OutOfStock'
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(f"""<html><head><script type="application/ld+json">
        {{"@context": "https://schema.org/", "@type": "Product", "name": "Test Product",
          "offers": {{"@type": "Offer", "priceCurrency": "AUD", "price": "{price}",
                     "availability": "https://schema.org/{availability}"}}}}
        </script></head><body>Product page</body></html>""")


def _latest_row(socketio_client, uuid, seconds=5):
    """The newest row sent for this watch among what arrives over the next few seconds (its html), or None"""
    latest = None
    for _ in range(seconds * 4):
        for event in socketio_client.get_received():
            if event['name'] == 'watch_row' and event['args'][0]['uuid'] == uuid:
                latest = event['args'][0]['html']
        time.sleep(0.25)
    return latest


def _list_page(app, client, uuids, tag=''):
    """A browser with the watch list open, filtered by the group `tag` (or not)"""
    page = app.extensions['socketio'].test_client(app, flask_test_client=client)
    assert page.is_connected()
    page.emit('watch-subscribe', {'uuids': uuids, 'rows_for_tag': tag})
    page.get_received()
    return page


def test_watch_list_row_is_sent_with_stock_and_price(client, live_server, measure_memory_usage, datastore_path):
    """A restock watch that was just added has "No information" in its row. The price and stock of its first check
    (or any later change) only showed after a reload: the realtime update did not carry them."""
    from changedetectionio.flask_app import app
    datastore = client.application.config.get('DATASTORE')

    _set_restock_product(datastore_path, price='10.00')
    # Paused: the list as it is right after adding the watch, before its first check
    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True),
                               extras={'processor': 'restock_diff', 'fetch_backend': 'html_requests', 'paused': True})

    res = client.get(url_for("watchlist.index"))
    assert b'restock-info-wrap' in res.data and b'No information' in res.data

    page = _list_page(app, client, [uuid])

    # The first check
    datastore.data['watching'][uuid]['paused'] = False
    client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    row = _latest_row(page, uuid)
    assert row, "The page showing the watch was sent its row"
    assert row.count('<tr') == 1 and f'data-watch-uuid="{uuid}"' in row
    assert 'In stock' in row and '10.00' in row and 'No information' not in row
    assert 'has-restock-info' in row and 'checking-now' not in row, "With its state as the list draws it"

    # What was sent is what a reload of the list shows
    res = client.get(url_for("watchlist.index"))
    assert b'In stock' in res.data and b'10.00' in res.data and b'No information' not in res.data

    # A new price and out of stock arrive the same way
    _set_restock_product(datastore_path, price='7.50', in_stock=False)
    client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    row = _latest_row(page, uuid)
    assert 'Not in stock' in row and '7.50' in row
    assert 'price-change down' in row, "With the change since the previous price, as in the list"

    page.disconnect()
    delete_all_watches(client)


def test_watch_list_row_is_sent_with_groups_and_title(client, live_server, measure_memory_usage, datastore_path):
    """A group given to a watch after the page was loaded (the "Group" action, its edit page in another tab) was
    not shown until a reload."""
    from changedetectionio.flask_app import app
    from changedetectionio.blueprint.tags.colour import tag_display_colours
    datastore = client.application.config.get('DATASTORE')
    tags = datastore.data['settings']['application']['tags']

    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True), extras={'paused': True})
    other = datastore.add_watch(url=url_for('test_endpoint', _external=True) + '?other', extras={'paused': True})
    page = _list_page(app, client, [uuid, other])

    # The "Group" action of the watch list, with a group that did not exist when the page was loaded
    client.post(url_for("ui.form_watch_list_checkbox_operations"),
                data={"op": "assign-tag", "uuids": [uuid], "op_extradata": "Made after the page loaded"}, follow_redirects=True)
    received = page.get_received()
    rows = {event['args'][0]['uuid']: event['args'][0]['html'] for event in received if event['name'] == 'watch_row'}
    assert other not in rows, "Only the watch that changed"
    row = rows[uuid]

    tag_uuid = next(iter(tags))
    assert 'Made after the page loaded' in row
    assert url_for('watchlist.index', tag=tag_uuid) in row, "A link to the group's watches"
    # In the group's colours by itself: the page's own colour rules are from before the group existed
    colours = tag_display_colours(tags[tag_uuid])
    assert f"--tag-chip-bg: {colours['light']['bg']}" in row and f"--tag-chip-dark-bg: {colours['dark']['bg']}" in row

    # Saved on its edit page (another tab): a second group, and a title
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid),
        data={"url": url_for('test_endpoint', _external=True), "tags": "Made after the page loaded, From the edit page",
              "title": "A <b>title</b> of its own", "fetch_backend": "html_requests", "time_between_check_use_default": "y"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    row = _latest_row(page, uuid, seconds=2)
    assert 'Made after the page loaded' in row and 'From the edit page' in row
    assert 'A &lt;b&gt;title&lt;/b&gt; of its own' in row and '<b>title</b>' not in row, "As text"

    # Paused: the state of the row comes with it, there is nothing for the page to work out
    client.post(url_for("ui.form_watch_list_checkbox_operations"), data={"op": "pause", "uuids": [uuid]}, follow_redirects=True)
    row = _latest_row(page, uuid, seconds=2)
    assert re.search(r'<tr[^>]*class="[^"]*\bpaused\b', row)

    page.disconnect()
    tags.clear()
    delete_all_watches(client)


def test_watch_list_row_is_sent_as_the_filtered_list_shows_it(client, live_server, measure_memory_usage, datastore_path):
    """The buttons of a row come back to the list as it is filtered (Edit, Recheck, pause carry the group), so a
    list filtered by a group is sent rows rendered for that group, and only if it asked for rows at all."""
    from changedetectionio.flask_app import app
    datastore = client.application.config.get('DATASTORE')
    tags = datastore.data['settings']['application']['tags']
    tag_uuid = datastore.add_tag(title='Filtered by this')
    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True), extras={'paused': True}, tag_uuids=[tag_uuid])

    whole_list = _list_page(app, client, [uuid])
    filtered_list = _list_page(app, client, [uuid], tag=tag_uuid)
    # The page of the watch itself (edit, preview ...) follows the watch but has no list to put a row in
    not_a_list = app.extensions['socketio'].test_client(app, flask_test_client=client)
    not_a_list.emit('watch-subscribe', {'uuids': [uuid]})
    # A group that does not exist is not a room to be let into
    made_up = app.extensions['socketio'].test_client(app, flask_test_client=client)
    made_up.emit('watch-subscribe', {'uuids': [uuid], 'rows_for_tag': 'no-such-group'})
    for page in (not_a_list, made_up):
        page.get_received()

    client.post(url_for("ui.form_watch_list_checkbox_operations"), data={"op": "mute", "uuids": [uuid]}, follow_redirects=True)

    plain = _latest_row(whole_list, uuid, seconds=2)
    filtered = _latest_row(filtered_list, uuid, seconds=1)
    assert plain and filtered and 'notification_muted' in plain

    edit_link = url_for('ui.ui_edit.edit_page', uuid=uuid)
    assert f'{edit_link}#general' in plain or f'href="{edit_link}"' in plain
    assert f'tag={tag_uuid}' not in plain.replace(url_for('watchlist.index', tag=tag_uuid), ''), "No group in the buttons of the whole list"
    assert url_for('ui.ui_edit.edit_page', uuid=uuid, tag=tag_uuid) in filtered, "Edit comes back to the filtered list"
    import html
    assert url_for('ui.form_watch_checknow', uuid=uuid, tag=tag_uuid) in html.unescape(filtered), "And so does Recheck"

    for page, what in ((not_a_list, "A page that is not a list"), (made_up, "A page asking for a group that is not there")):
        events = [event['name'] for event in page.get_received()]
        assert 'watch_row' not in events, f"{what} is not sent rows"
        assert 'watch_update' in events, "But still hears about the watch"

    for page in (whole_list, filtered_list, not_a_list, made_up):
        page.disconnect()
    tags.clear()
    delete_all_watches(client)


def test_watch_list_row_is_sent_with_the_sub_path_of_the_page(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    """The app served under a sub-path (USE_X_SETTINGS and X-Forwarded-Prefix, example.com/our-changedetection/):
    every address in a page starts with that path. A row is rendered from a worker thread, outside any request, so
    it has to be told: it was sent with addresses from the root ("/static/images/..."), which are not the app's."""
    import re
    from changedetectionio.flask_app import app
    monkeypatch.setenv('USE_X_SETTINGS', 'true')
    datastore = client.application.config.get('DATASTORE')
    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True), extras={'paused': True, 'fetch_backend': 'html_webdriver'})
    prefix = '/our-changedetection'

    def page_under(forwarded_prefix, page_says=None):
        """A watch list reached under `forwarded_prefix`. page_says: the sub-path the page gives itself when it
        asks for rows, as the page does; None for a page that does not say (the connection is asked then)."""
        page = app.extensions['socketio'].test_client(app, flask_test_client=client,
                                                      headers={'X-Forwarded-Prefix': forwarded_prefix} if forwarded_prefix is not None else None)
        assert page.is_connected()
        asks = {'uuids': [uuid], 'rows_for_tag': ''}
        if page_says is not None:
            asks['rows_url_prefix'] = page_says
        page.emit('watch-subscribe', asks)
        page.get_received()
        return page

    under_sub_path = page_under(prefix)
    at_the_root = page_under(None)
    # Not a path: taken as no sub-path, never put into the row
    not_a_path = page_under('/x"><script>alert(1)</script>')
    elsewhere = page_under('//evil.example.com')
    # The page says its sub-path itself and the proxy sends no header for the Socket.IO address (a "location" of
    # its own for the websocket): what the page says is what its addresses were made with
    page_says_it = page_under(None, page_says=prefix)
    # And what the page says is checked the same way
    page_says_markup = page_under(None, page_says='/x"><script>alert(1)</script>')

    client.post(url_for("ui.form_watch_list_checkbox_operations"), data={"op": "mute", "uuids": [uuid]}, follow_redirects=True)

    def addresses(row):
        """Every address of the app in the row: links, images, form actions"""
        found = re.findall(r'(?:href|src|action|formaction)="([^"]*)"', row)
        return [a for a in found if a.startswith('/')]

    row = _latest_row(under_sub_path, uuid, seconds=2)
    assert row and 'notification_muted' in row
    local = addresses(row)
    assert len(local) > 5, "The row has its links, buttons and images"
    assert all(a.startswith(prefix + '/') for a in local), [a for a in local if not a.startswith(prefix + '/')]
    # The one from the report: the icon of the browser the watch is fetched with
    assert f'src="{prefix}/static/images/google-chrome-icon.png' in row

    row = _latest_row(page_says_it, uuid, seconds=1)
    assert row and f'src="{prefix}/static/images/google-chrome-icon.png' in row, "The sub-path the page gave is used"

    for page, what in ((at_the_root, "A page at the root"), (not_a_path, "A prefix that is not a path"), (elsewhere, "A prefix that is another site"),
                       (page_says_markup, "A page giving markup as its sub-path")):
        row = _latest_row(page, uuid, seconds=1)
        assert row, what
        assert prefix not in row and 'evil.example.com' not in row and '<script>alert' not in row, what
        assert 'src="/static/images/google-chrome-icon.png' in row, f"{what}: addresses from the root"

    # Without USE_X_SETTINGS the header is anybody's to send and means nothing
    monkeypatch.delenv('USE_X_SETTINGS')
    not_trusted = page_under(prefix, page_says=prefix)
    client.post(url_for("ui.form_watch_list_checkbox_operations"), data={"op": "unmute", "uuids": [uuid]}, follow_redirects=True)
    row = _latest_row(not_trusted, uuid, seconds=2)
    assert row and prefix not in row

    for page in (under_sub_path, at_the_root, not_a_path, elsewhere, page_says_it, page_says_markup, not_trusted):
        page.disconnect()
