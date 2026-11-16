#!/usr/bin/env python3

import time
from flask import url_for
import os
from ..util import live_server_setup, wait_for_all_checks
import logging


# Requires playwright to be installed
def test_fetch_webdriver_content(client, live_server, measure_memory_usage, datastore_path):
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
        url_for("ui.ui_preview.preview_page", uuid="first"),
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


def test_favicon_falls_back_to_the_browsers_own_copy(client, live_server, measure_memory_usage, datastore_path):
    """When page script isn't allowed to read the icon, the one the browser fetched for itself is saved instead."""
    import base64
    import pytest
    from changedetectionio.strtobool import strtobool

    # This file also runs in the playwright and selenium CI jobs, only the puppeteer one has the fallback
    if not strtobool(os.getenv('FAST_PUPPETEER_CHROME_FETCHER', 'False')):
        pytest.skip("The browser-request favicon fallback is only in the puppeteer fetcher for now")
    assert os.getenv('PLAYWRIGHT_DRIVER_URL'), "Needs PLAYWRIGHT_DRIVER_URL set for this test"

    def _cdio(url):
        # The browser runs in another container in CI and reaches the test server as 'cdio'
        return url.replace('localhost.localdomain', 'cdio').replace('localhost', 'cdio')

    client.post(
        url_for("settings.settings_page"),
        data={
            "application-empty_pages_are_a_change": "",
            "requests-time_between_check-minutes": 180,
            'application-fetch_backend': "html_webdriver",
            'application-ui-favicons_enabled': "y",
        },
        follow_redirects=True
    )

    datastore = live_server.app.config['DATASTORE']
    uuid = datastore.add_watch(url=_cdio(url_for('test_favicon_page', key='fallback', _external=True)))
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    watch = datastore.data['watching'][uuid]
    assert not watch.get('last_error'), watch.get('last_error')

    # The test is only worth something if the in-page attempt really was made and refused
    # Asked over HTTP: the test endpoints run in the live server's own process
    import requests
    seen = requests.get(url_for('test_favicon_requests', key='fallback', _external=True)).json()['requested_by']
    assert 'browser' in seen, f"The browser never asked for the icon itself, saw {seen}"
    assert 'script' in seen, f"The in-page favicon fetch was never attempted, saw {seen}"

    assert watch.get_favicon_filename() == 'favicon.png', "The icon the browser fetched for itself was not saved"
    res = client.get(url_for('static_content', group='favicon', filename=uuid))
    assert res.status_code == 200
    assert res.data.startswith(b'\x89PNG')

    client.post(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
