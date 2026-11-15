#!/usr/bin/env python3

"""The full page screenshot of a page that animates and draws itself by script.

The page's scripts are held still while each screenshot chunk is taken (an animating page otherwise
keeps the capture waiting behind its repaints), but not before the page has reacted to the tall
screenshot viewport and to being scrolled - or it is drawn as it was before either happened.
"""

import os
from flask import url_for
from ..util import wait_for_all_checks


def _cdio(url):
    # The browser runs in another container in CI and reaches the test server as 'cdio'
    return url.replace('localhost.localdomain', 'cdio').replace('localhost', 'cdio')


def _is(pixel, red, green, blue):
    # The screenshot is a JPEG, so near enough
    return all(abs(a - b) < 60 for a, b in zip(pixel[:3], (red, green, blue)))


def test_screenshot_of_animated_page_shows_what_its_scripts_drew(client, live_server, measure_memory_usage, datastore_path):
    from PIL import Image

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
    uuid = datastore.add_watch(url=_cdio(url_for('test_animated_tall_page', _external=True)))
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    watch = datastore.data['watching'][uuid]
    assert not watch.get('last_error'), watch.get('last_error')
    assert 'The animated page text is here' in watch.get_history_snapshot(list(watch.history.keys())[-1])

    screenshot = Image.open(watch.get_screenshot()).convert('RGB')
    # 15000px of page, taken as two chunks
    assert screenshot.height > 10000, f"Expected the whole page in the screenshot, it is {screenshot.size}"
    middle = screenshot.width // 2

    assert _is(screenshot.getpixel((middle, 200)), 0, 160, 0), \
        "The page was held still before it could react to the screenshot viewport"
    # Not scrolled in the first chunk, scrolled in the second: the fixed band is 400px from the top of each
    assert _is(screenshot.getpixel((middle, 600)), 255, 0, 0)
    assert _is(screenshot.getpixel((middle, 10600)), 0, 0, 255), \
        "The page was held still before it could react to being scrolled for the second chunk"

    client.post(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
