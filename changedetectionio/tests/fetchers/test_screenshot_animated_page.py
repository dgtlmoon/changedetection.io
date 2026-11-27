#!/usr/bin/env python3

"""The full page screenshot of a tall page that never stops animating.

The puppeteer fetcher takes the first screen as it is and the rest in bands beyond the viewport,
without making the viewport taller or scrolling: the page is drawn the way a visitor has it, not
with everything that is sized to the viewport stretched to the height of a band and a fixed header
repeated in each one. Very large canvases below the first screen are left blank.
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


def test_screenshot_of_animated_tall_page(client, live_server, measure_memory_usage, datastore_path):
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
    client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    watch = datastore.data['watching'][uuid]
    assert not watch.get('last_error'), watch.get('last_error')
    assert 'The animated page text is here' in watch.get_history_snapshot(list(watch.history.keys())[-1])

    screenshot = Image.open(watch.get_screenshot()).convert('RGB')
    assert screenshot.height > 10000, f"Expected the whole page in the screenshot, it is {screenshot.size}"

    if not os.getenv('FAST_PUPPETEER_CHROME_FETCHER'):
        # The playwright fetcher still makes the viewport taller and scrolls
        client.post(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
        return

    middle = screenshot.width // 2
    white = (255, 255, 255)
    assert screenshot.height == 15000, "The screenshot should be exactly as tall as the page"
    assert _is(screenshot.getpixel((middle, 20)), 0, 0, 255), "The fixed header belongs at the top"
    assert _is(screenshot.getpixel((middle, 60)), 0, 160, 0)
    assert _is(screenshot.getpixel((middle, 200)), 0, 255, 255), "The first screen is drawn with everything on it, also a very large canvas"
    assert _is(screenshot.getpixel((middle, 6100)), *white), "A very large canvas below the first screen is left blank"
    assert _is(screenshot.getpixel((middle, 13100)), 255, 165, 0), "A canvas the size of a graph is drawn wherever it is"
    assert _is(screenshot.getpixel((middle, 5000)), *white), \
        "The viewport-high hero reaches 5000px down, the viewport was made taller for the screenshot"
    assert _is(screenshot.getpixel((middle, 10020)), *white), "The fixed header was drawn again in the second band"
    assert _is(screenshot.getpixel((middle, 12200)), 255, 0, 255), "The second band is not where it belongs"

    client.post(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
