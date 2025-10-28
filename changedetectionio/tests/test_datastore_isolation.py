#!/usr/bin/env python3
"""Test to verify client and live_server share the same datastore"""

def test_client_and_live_server_share_datastore(client, live_server):
    """Verify that client and live_server use the same app and datastore."""

    # They should be the SAME object
    assert client.application is live_server.app, "client.application and live_server.app should be the SAME object!"

    # They should share the same datastore
    client_datastore = client.application.config.get('DATASTORE')
    server_datastore = live_server.app.config.get('DATASTORE')

    assert client_datastore is server_datastore, \
        f"Datastores are DIFFERENT objects! client={hex(id(client_datastore))} server={hex(id(server_datastore))}"

    print(f"✓ client.application and live_server.app are the SAME object")
    print(f"✓ Both use the same DATASTORE at {hex(id(client_datastore))}")
    print(f"✓ Datastore path: {client_datastore.datastore_path}")
