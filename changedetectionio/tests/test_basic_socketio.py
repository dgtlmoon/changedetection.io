#!/usr/bin/env python3

import time
from flask import url_for
from .util import (
    set_original_response,
    set_modified_response,
    live_server_setup,
    wait_for_all_checks
)
from loguru import logger

def run_socketio_watch_update_test(client, live_server, password_mode=""):
    """Test that the socketio emits a watch update event when content changes"""

    # Set up the test server
    set_original_response()

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

    # Clear any initial messages
    socketio_test_client.get_received()

    # Make a change to trigger an update
    set_modified_response()

    # Force recheck
    res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    assert b'Queued 1 watch for rechecking.' in res.data

    # Wait for the watch to be checked
    wait_for_all_checks(client)

    has_watch_update = False
    has_unviewed_update = False

    for i in range(10):
        # Get received events
        received = socketio_test_client.get_received()

        if received:
            logger.info(f"Received {len(received)} events after {i+1} seconds")

            # Check for watch_update events with unviewed=True
            for event in received:
                if event['name'] == 'watch_update':
                    has_watch_update = True
                    if event['args'][0]['watch'].get('unviewed', False):
                        has_unviewed_update = True
                        logger.info("Found unviewed update event!")
                        break

        if has_unviewed_update:
            break

        # Force a recheck every 5 seconds to ensure events are emitted
#        if i > 0 and i % 5 == 0:
#            print(f"Still waiting for events, forcing another recheck...")
#            res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
#            assert b'Queued 1 watch for rechecking.' in res.data
#            wait_for_all_checks(client)

#        print(f"Waiting for unviewed update event... {i+1}/{max_wait}")
        time.sleep(1)

    # Verify we received watch_update events
    assert has_watch_update, "No watch_update events received"

    # Verify we received an unviewed event
    assert has_unviewed_update, "No watch_update event with unviewed=True received"

    # Alternatively, check directly if the watch in the datastore is marked as unviewed
    from changedetectionio.flask_app import app
    datastore = app.config.get('DATASTORE')

    watch_uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))

    # Get the watch from the datastore
    watch = datastore.data['watching'].get(watch_uuid)
    assert watch, f"Watch {watch_uuid} not found in datastore"
    assert watch.has_unviewed, "The watch was not marked as unviewed after content change"

    # Clean up
    client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)

def test_everything(live_server, client):

   #  live_server_setup(live_server) # Setup on conftest per function

    run_socketio_watch_update_test(password_mode="", live_server=live_server, client=client)

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

    run_socketio_watch_update_test(password_mode="not logged in, should exit on connect", live_server=live_server, client=client)
    res = client.post(
        url_for("login"),
        data={"password": "foobar"},
        follow_redirects=True
    )

    # Yes we are correctly logged in
    assert b"LOG OUT" in res.data
    run_socketio_watch_update_test(password_mode="should be like normal", live_server=live_server, client=client)
