#!/usr/bin/env python3

from flask import url_for


def test_darkmode_follows_device_unless_cookie_set(client, live_server, measure_memory_usage, datastore_path):
    # No cookie - "auto", the CSS follows prefers-color-scheme
    client.delete_cookie('css_dark_mode')
    res = client.get(url_for("watchlist.index"), follow_redirects=True)
    assert b'data-darkmode="auto"' in res.data

    # The cookie from the menu toggle always wins over the device setting
    client.set_cookie('css_dark_mode', 'true')
    res = client.get(url_for("watchlist.index"), follow_redirects=True)
    assert b'data-darkmode="true"' in res.data

    client.set_cookie('css_dark_mode', 'false')
    res = client.get(url_for("watchlist.index"), follow_redirects=True)
    assert b'data-darkmode="false"' in res.data

    # Garbage cookie value falls back to the device setting instead of erroring
    client.set_cookie('css_dark_mode', 'banana')
    res = client.get(url_for("watchlist.index"), follow_redirects=True)
    assert res.status_code == 200
    assert b'data-darkmode="auto"' in res.data

    client.delete_cookie('css_dark_mode')
