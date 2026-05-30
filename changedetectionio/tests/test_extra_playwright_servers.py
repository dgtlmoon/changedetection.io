#!/usr/bin/env python3

# Feature test for "Extra Playwright Servers".
#
# Exercises the configuration surface of the feature without needing a real
# browser: saving a server in Settings, the datastore filtering/exposing it, and
# it appearing as a selectable "Fetch Method" on the watch edit page. (The actual
# fetch routing through a server is a browser-based integration test, mirroring
# tests/custom_browser_url.)

from flask import url_for


def test_extra_playwright_server_setting_and_selection(client, live_server, measure_memory_usage, datastore_path):

    server_name = "Test PW Server"
    server_url = "ws://test-playwright-server:3000"

    # Save settings: one complete server, plus one incomplete entry (name, no URL)
    res = client.post(
        url_for("settings.settings_page"),
        data={
            "application-empty_pages_are_a_change": "",
            "requests-time_between_check-minutes": 180,
            "application-fetch_backend": "html_requests",
            # complete entry
            "requests-extra_playwright_servers-0-playwright_server_name": server_name,
            "requests-extra_playwright_servers-0-playwright_server_url": server_url,
            # incomplete entry (missing URL) - should be ignored by the datastore
            "requests-extra_playwright_servers-1-playwright_server_name": "incomplete-server",
            "requests-extra_playwright_servers-1-playwright_server_url": "",
        },
        follow_redirects=True
    )
    assert b"Settings updated." in res.data

    datastore = client.application.config.get('DATASTORE')

    # Persisted into the settings structure
    stored = datastore.data['settings']['requests']['extra_playwright_servers']
    assert any(
        s.get('playwright_server_name') == server_name and s.get('playwright_server_url') == server_url
        for s in stored
    )

    # Exposed as a fetch-backend choice tuple, with the incomplete one filtered out
    servers = datastore.extra_playwright_servers
    assert ("extra_playwright_server_" + server_name, server_name) in servers
    assert not any(name == "incomplete-server" for (_, name) in servers), \
        "A server with a missing URL should be filtered out"

    # It should now be offered as a "Fetch Method" on the watch edit page
    datastore.add_watch(url='https://example.com')
    res = client.get(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        follow_redirects=True
    )
    assert b"extra_playwright_server_" in res.data
    assert server_name.encode() in res.data
    # The incomplete server must not be offered
    assert b"incomplete-server" not in res.data


def test_extra_playwright_server_rejects_non_ws_url(client, live_server, measure_memory_usage, datastore_path):
    # The Playwright server URL must start with ws:// or wss://
    res = client.post(
        url_for("settings.settings_page"),
        data={
            "application-empty_pages_are_a_change": "",
            "requests-time_between_check-minutes": 180,
            "application-fetch_backend": "html_requests",
            "requests-extra_playwright_servers-0-playwright_server_name": "bad-scheme",
            "requests-extra_playwright_servers-0-playwright_server_url": "http://not-a-websocket:3000",
        },
        follow_redirects=True
    )
    assert b"Settings updated." not in res.data
    assert b"must start with wss:// or ws://" in res.data
