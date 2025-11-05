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
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

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
    res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    assert b'Queued 1 watch for rechecking.' in res.data

    wait_for_all_checks(client)

    # Now something should be ready, indicated by having a 'has-unread-changes' class
    res = client.get(url_for("watchlist.index"))
    assert b'has-unread-changes' in res.data

    # The original checksum should be not be here anymore (cdio adds it to the bottom of the text)

    res = client.get(
        url_for("ui.ui_views.preview_page", uuid="first"),
        follow_redirects=True
    )

    assert original_md5.encode('utf-8') not in res.data
    assert changed_md5.encode('utf-8') in res.data

    res = client.get(
        url_for("ui.ui_views.diff_history_page", uuid="first"),
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


    