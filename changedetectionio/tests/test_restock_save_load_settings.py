#!/usr/bin/env python3
import os
import time
from flask import url_for
from .util import live_server_setup, wait_for_all_checks, extract_UUID_from_client

def test_restock_settings_persistence(client, live_server):
    """Test that restock processor and settings are correctly saved and loaded after app restart"""
    
    live_server_setup(live_server)
    
    # Create a test page with pricing information
    test_return_data = """<html>
       <body>
     Some initial text<br>
     <p>Which is across multiple lines</p>
     <br>
     So let's see what happens.  <br>
     <div>price: $10.99</div>
     <div id="sametext">Out of stock</div>
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)
    
    # Add our URL to the import page (pointing to our test endpoint)
    test_url = url_for('test_endpoint', _external=True)
    
    # Add a new watch with the restock_diff processor
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": '', 'processor': 'restock_diff'},
        follow_redirects=True
    )
    
    # Wait for initial check to complete
    wait_for_all_checks(client)
    
    # Get the UUID of the watch
    uuid = extract_UUID_from_client(client)
    
    # Set custom restock settings
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid),
        data={
            "url": test_url,
            "tags": "",
            "headers": "",
            "restock_settings-price_change_min": 10,
            "restock_settings-price_change_threshold_percent": 5,
            'fetch_backend': "html_requests"
        },
        follow_redirects=True
    )
    
    assert b"Updated watch." in res.data
    
    # Verify the settings were saved in the current datastore
    app_config = client.application.config.get('DATASTORE').data
    watch = app_config['watching'][uuid]
    
    assert watch.get('processor') == 'restock_diff'
    assert watch['restock_settings'].get('price_change_min') == 10
    assert watch['restock_settings'].get('price_change_threshold_percent') == 5
    
    # Restart the application by calling teardown and recreating the datastore
    # This simulates shutting down and restarting the app
    datastore = client.application.config.get('DATASTORE')
    datastore.stop_thread = True
    datastore.sync_to_json()  # Force write to disk before recreating
    
    # Create a new datastore instance that will read from the saved JSON
    from changedetectionio import store
    new_datastore = store.ChangeDetectionStore(datastore_path="./test-datastore", include_default_watches=False)
    client.application.config['DATASTORE'] = new_datastore
    
    # Verify the watch settings were correctly loaded after restart
    app_config = client.application.config.get('DATASTORE').data
    watch = app_config['watching'][uuid]
    
    # Check that processor mode is correctly preserved
    assert watch.get('processor') == 'restock_diff', "Watch processor mode should be preserved as 'restock_diff'"
    
    # Check that the restock settings were correctly preserved
    assert watch['restock_settings'].get('price_change_min') == 10, "price_change_min setting should be preserved"
    assert watch['restock_settings'].get('price_change_threshold_percent') == 5, "price_change_threshold_percent setting should be preserved"