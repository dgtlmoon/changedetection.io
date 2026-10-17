#!/usr/bin/env python3

"""A PDF fetched with a browser fetcher must be detected and compared on the PDF itself.

Chrome hands a PDF to its built-in viewer, so the page content is only the viewer's HTML wrapper,
which is the same for every version of the document. Fetchers with supports_pdf (puppeteer) must
supply the original PDF, the others must give a clear error once and then fall back to html_requests.
"""

import os
import shutil
from flask import url_for
from ..util import wait_for_all_checks


def _cdio(url):
    # The browser runs in another container in CI and reaches the test server as 'cdio'
    return url.replace('localhost.localdomain', 'cdio').replace('localhost', 'cdio')


def _recheck(client):
    res = client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
    assert b'Queued 1 watch for rechecking.' in res.data
    wait_for_all_checks(client)


def test_pdf_in_browser_fetcher(client, live_server, measure_memory_usage, datastore_path):
    assert os.getenv('PLAYWRIGHT_DRIVER_URL'), "Needs PLAYWRIGHT_DRIVER_URL set for this test"
    from changedetectionio import content_fetchers

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

    shutil.copy("tests/test.pdf", os.path.join(datastore_path, "endpoint-test.pdf"))

    # Query string so the URL doesn't end in .pdf, only the response says it's a PDF
    test_url = _cdio(url_for('test_pdf_endpoint', _external=True)) + '?download=1'
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data
    wait_for_all_checks(client)

    uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))
    watch = live_server.app.config['DATASTORE'].data['watching'][uuid]

    if content_fetchers.html_webdriver.supports_pdf:
        # The browser supplied the PDF itself
        assert not watch.get('last_error'), watch.get('last_error')
        assert watch.get_screenshot(), "PDF should have been fetched by the browser (which gives a screenshot)"
    else:
        # The browser could only see the PDF viewer, the next check falls back to html_requests.
        # A duplicate queue entry (scheduler + import) can run that next check straight after the
        # first one, so by now it may have already recovered - both outcomes are correct here.
        # (The error itself is checked without timing issues in tests/test_pdf.py)
        assert watch.is_pdf
        if watch.get('last_error'):
            assert 'could not provide the original PDF' in watch.get('last_error')
            assert not watch.history_n
            _recheck(client)
        assert not watch.get('last_error'), watch.get('last_error')

    assert watch.history_n == 1
    snapshot = watch.get_history_snapshot(timestamp=list(watch.history.keys())[-1])
    assert 'hello world' in snapshot
    assert 'html' not in snapshot.lower()
    # The original PDF is kept, whichever fetcher got it
    with open("tests/test.pdf", 'rb') as f:
        assert watch.get_fetched_pdf(list(watch.history.keys())[-1]) == f.read()

    # Same PDF again - nothing changed, no new snapshot
    _recheck(client)
    assert not watch.get('last_error'), watch.get('last_error')
    assert watch.history_n == 1

    # New version of the PDF - must be seen as a change
    shutil.copy("tests/test2.pdf", os.path.join(datastore_path, "endpoint-test.pdf"))
    _recheck(client)
    assert not watch.get('last_error'), watch.get('last_error')
    assert watch.history_n == 2
    snapshot = watch.get_history_snapshot(timestamp=list(watch.history.keys())[-1])
    assert 'here is a change' in snapshot
    # Both versions are kept for comparing
    first_version, second_version = list(watch.history.keys())
    with open("tests/test.pdf", 'rb') as f:
        assert watch.get_fetched_pdf(first_version) == f.read()
    with open("tests/test2.pdf", 'rb') as f:
        assert watch.get_fetched_pdf(second_version) == f.read()
