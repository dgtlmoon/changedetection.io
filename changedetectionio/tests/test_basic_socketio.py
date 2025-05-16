#!/usr/bin/env python3

import time
from flask import url_for
from .util import (
    set_original_response,
    set_modified_response,
    live_server_setup,
    wait_for_all_checks
)

class TestSocketIO:
    """Test class for Socket.IO functionality"""
    
    def test_socketio_watch_update(self, client, live_server):
        """Test that the socketio emits a watch update event when content changes"""
    
        # Set up the test server
        set_original_response()
        live_server_setup(live_server)

        # Get the SocketIO instance from the app
        from changedetectionio.flask_app import app
        socketio = app.extensions['socketio']
        
        # Create a test client for SocketIO
        socketio_test_client = socketio.test_client(app, flask_test_client=client)
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

        # Wait for events to be emitted and received (up to 20 seconds)
        max_wait = 20
        has_watch_update = False
        has_unviewed_update = False
        
        for i in range(max_wait):
            # Get received events
            received = socketio_test_client.get_received()
            
            if received:
                print(f"Received {len(received)} events after {i+1} seconds")
                
                # Check for watch_update events with unviewed=True
                for event in received:
                    if event['name'] == 'watch_update':
                        has_watch_update = True
                        if event['args'][0].get('unviewed', False):
                            has_unviewed_update = True
                            print("Found unviewed update event!")
                            break
            
            if has_unviewed_update:
                break
                
            # Force a recheck every 5 seconds to ensure events are emitted
            if i > 0 and i % 5 == 0:
                print(f"Still waiting for events, forcing another recheck...")
                res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
                assert b'Queued 1 watch for rechecking.' in res.data
                wait_for_all_checks(client)
                
            print(f"Waiting for unviewed update event... {i+1}/{max_wait}")
            time.sleep(1)

        # Verify we received watch_update events
        assert has_watch_update, "No watch_update events received"

        # Verify we received an unviewed event
        assert has_unviewed_update, "No watch_update event with unviewed=True received"
        
        # Alternatively, check directly if the watch in the datastore is marked as unviewed
        from changedetectionio.flask_app import app
        datastore = app.config.get('DATASTORE')
        
        # Extract the watch UUID from the watchlist page
        res = client.get(url_for("watchlist.index"))
        import re
        m = re.search('edit/(.+?)[#"]', str(res.data))
        assert m, "Could not find watch UUID in page"
        watch_uuid = m.group(1).strip()
        
        # Get the watch from the datastore
        watch = datastore.data['watching'].get(watch_uuid)
        assert watch, f"Watch {watch_uuid} not found in datastore"
        assert watch.has_unviewed, "The watch was not marked as unviewed after content change"
        
        # Clean up
        client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)