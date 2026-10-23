#!/usr/bin/env python3

import re
from urllib.parse import urlsplit

from flask import url_for


def get_html_darkmode_state(res):
    # Read it from the <html> tag - the inline badge/tag CSS also contains html[data-darkmode="..."]
    m = re.search(rb'<html[^>]*\sdata-darkmode="([^"]*)"', res.data)
    return m.group(1).decode() if m else None


def test_darkmode_follows_device_unless_cookie_set(client, live_server, measure_memory_usage, datastore_path):
    # The test client defaults cookies to domain="localhost", which isn't sent to the
    # live_server's SERVER_NAME (localhost.localdomain), so set them for the real host
    cookie_domain = urlsplit(url_for("watchlist.index", _external=True)).hostname

    # No cookie - "auto", the CSS follows prefers-color-scheme
    client.delete_cookie('css_dark_mode', domain=cookie_domain)
    res = client.get(url_for("watchlist.index"), follow_redirects=True)
    assert get_html_darkmode_state(res) == 'auto'

    # The cookie from the menu toggle always wins over the device setting
    client.set_cookie('css_dark_mode', 'true', domain=cookie_domain)
    res = client.get(url_for("watchlist.index"), follow_redirects=True)
    assert get_html_darkmode_state(res) == 'true'

    client.set_cookie('css_dark_mode', 'false', domain=cookie_domain)
    res = client.get(url_for("watchlist.index"), follow_redirects=True)
    assert get_html_darkmode_state(res) == 'false'

    # Garbage cookie value falls back to the device setting instead of erroring
    client.set_cookie('css_dark_mode', 'banana', domain=cookie_domain)
    res = client.get(url_for("watchlist.index"), follow_redirects=True)
    assert res.status_code == 200
    assert get_html_darkmode_state(res) == 'auto'

    client.delete_cookie('css_dark_mode', domain=cookie_domain)
