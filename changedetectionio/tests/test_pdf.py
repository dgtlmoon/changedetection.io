#!/usr/bin/env python3

import time
from flask import url_for
from .util import set_original_response, set_modified_response, live_server_setup, wait_for_all_checks
import os


# `subtractive_selectors` should still work in `source:` type requests
def test_fetch_pdf(client, live_server, measure_memory_usage, datastore_path):
    import shutil
    import os

    shutil.copy("tests/test.pdf", os.path.join(datastore_path, "endpoint-test.pdf"))
    first_version_size = os.path.getsize(os.path.join(datastore_path, "endpoint-test.pdf"))

    test_url = url_for('test_pdf_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)

    wait_for_all_checks(client)

    watch = live_server.app.config['DATASTORE'].data['watching'][uuid]
    dates = list(watch.history.keys())
    snapshot_contents = watch.get_history_snapshot(timestamp=dates[0])

    # PDF header should not be there (it was converted to text)
    assert 'PDF' not in snapshot_contents
    # Was converted away from HTML
    assert 'pdftohtml' not in snapshot_contents.lower() # Generator tag shouldnt be there
    assert f'Original file size - {first_version_size}' in snapshot_contents
    assert 'html' not in snapshot_contents.lower() # is converted from html
    assert 'body' not in snapshot_contents.lower()  # is converted from html
    # And our text content was there
    assert 'hello world' in snapshot_contents

    # So we know if the file changes in other ways
    import hashlib
    original_md5 = hashlib.md5(open(os.path.join(datastore_path, "endpoint-test.pdf"), 'rb').read()).hexdigest().upper()
    # We should have one
    assert len(original_md5) >0
    # And it's going to be in the document
    assert f'Document checksum - {original_md5}' in snapshot_contents

    shutil.copy("tests/test2.pdf", os.path.join(datastore_path, "endpoint-test.pdf"))
    changed_md5 = hashlib.md5(open(os.path.join(datastore_path, "endpoint-test.pdf"), 'rb').read()).hexdigest().upper()
    res = client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
    assert b'Queued 1 watch for rechecking.' in res.data

    wait_for_all_checks(client)

    # Now something should be ready, indicated by having a 'has-unread-changes' class
    res = client.get(url_for("watchlist.index"))
    assert b'has-unread-changes' in res.data

    # The original checksum should be not be here anymore (cdio adds it to the bottom of the text)

    res = client.get(
        url_for("ui.ui_preview.preview_page", uuid="first"),
        follow_redirects=True
    )

    assert original_md5.encode('utf-8') not in res.data
    assert changed_md5.encode('utf-8') in res.data

    res = client.get(
        url_for("ui.ui_diff.diff_history_page", uuid="first"),
        follow_redirects=True
    )

    assert original_md5.encode('utf-8') in res.data
    assert changed_md5.encode('utf-8') in res.data
    assert b'here is a change' in res.data


    dates = list(watch.history.keys())
    # new snapshot was also OK, no HTML
    snapshot_contents = watch.get_history_snapshot(timestamp=dates[1])
    assert 'html' not in snapshot_contents.lower()
    assert f'Original file size - {os.path.getsize(os.path.join(datastore_path, "endpoint-test.pdf"))}' in snapshot_contents
    assert f'here is a change' in snapshot_contents
    assert os.path.getsize(os.path.join(datastore_path, "endpoint-test.pdf")) != first_version_size # And the disk change worked


    

def test_pdf_fetcher_resolution(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    # PDF watches only get moved to html_requests when the chosen fetcher can't supply the original PDF
    from changedetectionio import content_fetchers
    from changedetectionio.content_fetchers.puppeteer import fetcher as puppeteer_fetcher
    from changedetectionio.content_fetchers.webdriver_selenium import fetcher as selenium_fetcher

    datastore = client.application.config.get('DATASTORE')
    uuid = datastore.add_watch(url='http://example.com/some-document', extras={'fetch_backend': 'html_webdriver'})
    watch = datastore.data['watching'][uuid]
    watch['content-type'] = 'application/pdf'
    assert watch.is_pdf

    monkeypatch.setattr(content_fetchers, 'html_webdriver', selenium_fetcher)
    _, backend_name, _ = content_fetchers.resolve_content_fetcher(watch, datastore)
    assert backend_name == 'html_requests'
    assert watch.get_fetch_backend == 'html_requests'

    monkeypatch.setattr(content_fetchers, 'html_webdriver', puppeteer_fetcher)
    fetcher_class, backend_name, _ = content_fetchers.resolve_content_fetcher(watch, datastore)
    assert backend_name == 'html_webdriver'
    assert fetcher_class is puppeteer_fetcher
    assert watch.get_fetch_backend == 'html_webdriver'


def test_pdf_from_fetcher_without_pdf_support(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    # A fetcher that only has the browser's PDF viewer HTML should give a clear error, and the
    # content-type must be remembered so the next check knows it's a PDF
    import shutil
    from changedetectionio.content_fetchers.requests import fetcher as requests_fetcher

    shutil.copy("tests/test.pdf", os.path.join(datastore_path, "endpoint-test.pdf"))

    original_run = requests_fetcher.run

    async def run_like_a_browser(self, *args, **kwargs):
        await original_run(self, *args, **kwargs)
        self.content = '<html><body><embed type="application/pdf"></body></html>'
        self.raw_content = None

    monkeypatch.setattr(requests_fetcher, 'run', run_like_a_browser)

    # Query string so the URL doesn't end in .pdf, only the response content-type says it's a PDF
    test_url = url_for('test_pdf_endpoint', _external=True) + '?download=1'
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    watch = live_server.app.config['DATASTORE'].data['watching'][uuid]
    assert not watch.is_pdf
    client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    assert 'could not provide the original PDF' in watch.get('last_error')
    assert watch.is_pdf
    assert not watch.history

    # With a fetcher that can supply the PDF it works again
    monkeypatch.undo()
    client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    assert not watch.get('last_error')
    assert 'hello world' in watch.get_history_snapshot(timestamp=list(watch.history.keys())[0])


def test_pdf_last_two_versions_are_kept(client, live_server, measure_memory_usage, datastore_path):
    # The snapshot is only the converted text, the original PDFs of the newest two versions must be kept
    import shutil
    import glob

    test_url = url_for('test_pdf_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    watch = live_server.app.config['DATASTORE'].data['watching'][uuid]

    versions = ["tests/test.pdf", "tests/test2.pdf", "tests/test.pdf"]
    for i, source in enumerate(versions):
        shutil.copy(source, os.path.join(datastore_path, "endpoint-test.pdf"))
        client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
        wait_for_all_checks(client)
        assert watch.history_n == i + 1

        newest = list(watch.history.keys())[-2:]
        stored = sorted(os.path.basename(f) for f in glob.glob(os.path.join(watch.data_dir, "*.pdf"))
                        if os.path.basename(f)[:-4].isdigit())
        assert stored == sorted(f"{k}.pdf" for k in newest)

        # And it's the actual PDF that was fetched for that version
        with open(source, 'rb') as f:
            assert watch.get_fetched_pdf(newest[-1]) == f.read()

    # The oldest version was pruned
    assert watch.get_fetched_pdf(list(watch.history.keys())[0]) is False
