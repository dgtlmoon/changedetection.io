#!/usr/bin/env python3

"""A page that keeps the browser's main thread busy must not use up the whole fetch.

Everything the fetcher reads from a page (its content, the element positions, the stock text, the
favicon) is asked of the page's main thread. With an animation that is drawn without a GPU that
thread is hardly ever free, each read waited for a gap, and the fetch ended with "Browser connected
but was unable to process the page in 180 seconds" before it got to the screenshot. The puppeteer
fetcher holds the page's own scripts still while it reads, and does not wait on the favicon fetcher.
"""

import os
import pytest
from flask import url_for
from ..util import wait_for_all_checks


def _cdio(url):
    # The browser runs in another container in CI and reaches the test server as 'cdio'
    return url.replace('localhost.localdomain', 'cdio').replace('localhost', 'cdio')


def test_busy_page_is_fetched_without_waiting_on_it(client, live_server, measure_memory_usage, datastore_path):
    if not os.getenv('FAST_PUPPETEER_CHROME_FETCHER'):
        # Only the puppeteer fetcher holds the page still. The Playwright fetcher still reads this
        # page one gap at a time and is not done when wait_for_all_checks() gives up.
        pytest.skip("Only the puppeteer fetcher holds a busy page's scripts still while it reads it")

    assert os.getenv('PLAYWRIGHT_DRIVER_URL'), "Needs PLAYWRIGHT_DRIVER_URL set for this test"

    res = client.post(
        url_for("settings.settings_page"),
        data={
            "application-empty_pages_are_a_change": "",
            "requests-time_between_check-minutes": 180,
            'application-fetch_backend': "html_webdriver",
        },
        follow_redirects=True
    )
    assert b"Settings updated." in res.data

    datastore = live_server.app.config['DATASTORE']
    uuid = datastore.add_watch(url=_cdio(url_for('test_busy_page', key='busy', _external=True)))
    wait_for_all_checks(client)

    watch = datastore.data['watching'][uuid]
    assert not watch.get('last_error'), watch.get('last_error')
    assert 'The busy page text is here' in watch.get_history_snapshot(list(watch.history.keys())[-1])
    assert os.path.isfile(watch.get_screenshot())
    print(f"=== BUSY PAGE fetch_time {watch.get('fetch_time')}s", flush=True)

    # The page blocks for 8s at a time. Reading it one gap at a time took 100s, held still it is
    # the content-ready wait, one gap to get hold of the page, and the bounded wait for the favicon.
    assert watch.get('fetch_time') < 55, f"The fetch waited on the page for {watch.get('fetch_time')}s"

    client.post(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
