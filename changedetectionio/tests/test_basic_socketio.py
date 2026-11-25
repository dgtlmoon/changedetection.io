#!/usr/bin/env python3

import os
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


# The parts of a watch's row that plugins draw themselves go with its realtime update (watch_list_row_html hook)
RESTOCK_CELL = 'td.restock-and-price'


def _set_restock_product(datastore_path, price, in_stock=True):
    availability = 'InStock' if in_stock else 'OutOfStock'
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(f"""<html><head><script type="application/ld+json">
        {{"@context": "https://schema.org/", "@type": "Product", "name": "Test Product",
          "offers": {{"@type": "Offer", "priceCurrency": "AUD", "price": "{price}",
                     "availability": "https://schema.org/{availability}"}}}}
        </script></head><body>Product page</body></html>""")


def _latest_row_update(socketio_client, uuid, seconds=5):
    """The newest watch_update for this watch among what arrives over the next few seconds"""
    latest = None
    for _ in range(seconds * 4):
        for event in socketio_client.get_received():
            if event['name'] == 'watch_update' and event['args'][0]['watch']['uuid'] == uuid:
                latest = event['args'][0]['watch']
        time.sleep(0.25)
    return latest


def test_restock_stock_and_price_are_sent_with_the_row_update(client, live_server, measure_memory_usage, datastore_path):
    """The "Restock & Price" cell of the watch list is drawn with the list. A watch that was just added has
    "No information" there, and the price and stock of its first check (or any later change) only showed after a
    reload: the realtime update of the row did not carry them. The cell's template now goes with every update of
    the watch, through the watch_list_row_html plugin hook (processors/restock_diff/plugins/watch_list_cell.py)."""
    from changedetectionio.flask_app import app
    socketio = app.extensions['socketio']
    datastore = client.application.config.get('DATASTORE')

    _set_restock_product(datastore_path, price='10.00')
    # Paused: the list as it is right after adding the watch, before its first check
    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True),
                               extras={'processor': 'restock_diff', 'fetch_backend': 'html_requests', 'paused': True})

    res = client.get(url_for("watchlist.index"))
    assert b'restock-info-wrap' in res.data and b'No information' in res.data

    page_showing_the_list = socketio.test_client(app, flask_test_client=client)
    assert page_showing_the_list.is_connected()
    page_showing_the_list.emit('watch-subscribe', {'uuids': [uuid]})
    page_showing_the_list.get_received()

    # The first check
    datastore.data['watching'][uuid]['paused'] = False
    client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    row = _latest_row_update(page_showing_the_list, uuid)
    assert row, "The page showing the watch got its update"
    cell = row['row_html'][RESTOCK_CELL]
    assert 'restock-info-wrap' in cell
    assert 'In stock' in cell and 'No information' not in cell
    assert '10.00' in cell

    # What was sent is what a reload of the list shows
    res = client.get(url_for("watchlist.index"))
    assert b'In stock' in res.data and b'10.00' in res.data and b'No information' not in res.data

    # A new price and out of stock arrive the same way
    _set_restock_product(datastore_path, price='7.50', in_stock=False)
    client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    cell = _latest_row_update(page_showing_the_list, uuid)['row_html'][RESTOCK_CELL]
    assert 'Not in stock' in cell and '7.50' in cell and '10.00' not in cell.split('title=')[0]
    assert 'price-change down' in cell, "With the change since the previous price, as in the list"

    page_showing_the_list.disconnect()
    delete_all_watches(client)


def test_row_update_parts_from_plugins(client, live_server, measure_memory_usage, datastore_path):
    from changedetectionio.flask_app import app
    from changedetectionio.pluggy_interface import plugin_manager, collect_watch_list_row_html
    from changedetectionio.plugin_api import hookimpl

    datastore = client.application.config.get('DATASTORE')
    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True), extras={'paused': True})
    watch = datastore.data['watching'][uuid]

    with app.test_request_context():
        assert collect_watch_list_row_html(watch) == {}, "A text watch has no part of its row drawn by a plugin"

        class OneThatAddsAPart:
            @hookimpl
            def watch_list_row_html(self, watch):
                return {'.my-plugin-cell': f"<b>{watch.get('uuid')}</b>"}

        class OneThatBreaks:
            @hookimpl
            def watch_list_row_html(self, watch):
                raise RuntimeError("broken plugin")

        adds, breaks = OneThatAddsAPart(), OneThatBreaks()
        plugin_manager.register(adds, 'test_adds_a_row_part')
        try:
            assert collect_watch_list_row_html(watch) == {'.my-plugin-cell': f"<b>{uuid}</b>"}
            # A plugin that fails does not stop the row update from going out
            plugin_manager.register(breaks, 'test_breaks')
            try:
                assert isinstance(collect_watch_list_row_html(watch), dict)
            finally:
                plugin_manager.unregister(breaks)
        finally:
            plugin_manager.unregister(adds)

    delete_all_watches(client)
