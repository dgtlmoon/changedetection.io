#!/usr/bin/env python3

import time
from flask import url_for
import os
from ..util import live_server_setup, wait_for_all_checks
import logging


# Requires playwright to be installed
def test_fetch_webdriver_content(client, live_server, measure_memory_usage):
    #  live_server_setup(live_server) # Setup on conftest per function

    #####################
    res = client.post(
        url_for("settings.settings_page"),
        data={
            "application-empty_pages_are_a_change": "",
            "requests-time_between_check-minutes": 180,
            'application-fetch_backend': "html_webdriver",
            'application-ui-favicons_enabled': "y",
        },
        follow_redirects=True
    )

    assert b"Settings updated." in res.data

    # Add our URL to the import page
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": "https://changedetection.io/ci-test.html"},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data
    wait_for_all_checks(client)

    res = client.get(
        url_for("ui.ui_views.preview_page", uuid="first"),
        follow_redirects=True
    )
    logging.getLogger().info("Looking for correct fetched HTML (text) from server")
    assert b'cool it works' in res.data

    # Favicon scraper check, favicon only so far is fetched when in browser mode (not requests mode)
    if os.getenv("PLAYWRIGHT_DRIVER_URL"):
        uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))
        res = client.get(
            url_for("watchlist.index"),
        )
        # The UI can access it here
        assert f'src="/static/favicon/{uuid}'.encode('utf8') in res.data

        # Attempt to fetch it, make sure that works
        res = client.get(url_for('static_content', group='favicon', filename=uuid))
        assert res.status_code == 200
        assert len(res.data) > 10

        # Check the API also returns it
        api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')
        res = client.get(
            url_for("watchfavicon", uuid=uuid),
            headers={'x-api-key': api_key}
        )
        assert res.status_code == 200
        assert len(res.data) > 10

    ##################### disable favicons check
    res = client.post(
        url_for("settings.settings_page"),
        data={
            "requests-time_between_check-minutes": 180,
            'application-ui-favicons_enabled': "",
            "application-empty_pages_are_a_change": "",
        },
        follow_redirects=True
    )

    assert b"Settings updated." in res.data

    res = client.get(
        url_for("watchlist.index"),
    )
    # The UI can access it here
    assert f'src="/static/favicon'.encode('utf8') not in res.data
