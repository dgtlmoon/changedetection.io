#!/usr/bin/python3

import time
from flask import url_for
from .util import set_original_response, set_modified_response, live_server_setup

sleep_time_for_fetch_thread = 3

# `subtractive_selectors` should still work in `source:` type requests
def test_fetch_pdf(client, live_server):
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

    time.sleep(sleep_time_for_fetch_thread)
    res = client.get(
        url_for("preview_page", uuid="first"),
        follow_redirects=True
    )

    assert b'PDF-1.5' not in res.data
    assert b'hello world' in res.data

    # So we know if the file changes in other ways
    import hashlib
    md5 = hashlib.md5(open("test-datastore/endpoint-test.pdf", 'rb').read()).hexdigest().upper()
    # We should have one
    assert len(md5) >0
    # And it's going to be in the document
    assert b'Document checksum - '+bytes(str(md5).encode('utf-8')) in res.data