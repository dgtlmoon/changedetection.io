#!/usr/bin/env python3

import time
from flask import url_for
from .util import set_original_response, set_modified_response, live_server_setup, wait_for_all_checks


# `subtractive_selectors` should still work in `source:` type requests
def test_fetch_pdf(client, live_server, measure_memory_usage):
    import shutil
    shutil.copy("tests/test.pdf", "test-datastore/endpoint-test.pdf")

    live_server_setup(live_server)
    test_url = url_for('test_pdf_endpoint', _external=True)
    # Add our URL to the import page
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data

    wait_for_all_checks(client)

    res = client.get(
        url_for("preview_page", uuid="first"),
        follow_redirects=True
    )

    # PDF header should not be there (it was converted to text)
    assert b'PDF' not in res.data[:10]
    assert b'hello world' in res.data

    # So we know if the file changes in other ways
    import hashlib
    original_md5 = hashlib.md5(open("test-datastore/endpoint-test.pdf", 'rb').read()).hexdigest().upper()
    # We should have one
    assert len(original_md5) > 0
    # And it's going to be in the document
    assert b'Document checksum - ' + bytes(str(original_md5).encode('utf-8')) in res.data

    shutil.copy("tests/test2.pdf", "test-datastore/endpoint-test.pdf")
    changed_md5 = hashlib.md5(open("test-datastore/endpoint-test.pdf", 'rb').read()).hexdigest().upper()
    res = client.get(url_for("form_watch_checknow"), follow_redirects=True)
    assert b'1 watches queued for rechecking.' in res.data

    wait_for_all_checks(client)

    # Now something should be ready, indicated by having a 'unviewed' class
    res = client.get(url_for("index"))
    assert b'unviewed' in res.data

    # The original checksum should be not be here anymore (cdio adds it to the bottom of the text)

    res = client.get(
        url_for("preview_page", uuid="first"),
        follow_redirects=True
    )

    assert original_md5.encode('utf-8') not in res.data
    assert changed_md5.encode('utf-8') in res.data

    res = client.get(
        url_for("diff_history_page", uuid="first"),
        follow_redirects=True
    )

    assert original_md5.encode('utf-8') in res.data
    assert changed_md5.encode('utf-8') in res.data

    assert b'here is a change' in res.data
