#!/usr/bin/python3

from .util import set_original_response, set_modified_response, live_server_setup
from flask import url_for
from urllib.request import urlopen
from zipfile import ZipFile
import re
import time


def test_backup(client, live_server):
    live_server_setup(live_server)

    set_original_response()

    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URL to the import page
    res = client.post(
        url_for("import_page"),
        data={"urls": url_for('test_endpoint', _external=True)},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data
    time.sleep(3)

    res = client.get(
        url_for("get_backup"),
        follow_redirects=True
    )

    # Should get the right zip content type
    assert res.content_type == "application/zip"

    # Should be PK/ZIP stream
    assert res.data.count(b'PK') >= 2

    # ZipFile from buffer seems non-obvious, just save it instead
    with open("download.zip", 'wb') as f:
        f.write(res.data)

    zip = ZipFile('download.zip')
    l = zip.namelist()
    uuid4hex = re.compile('^[a-f0-9]{8}-?[a-f0-9]{4}-?4[a-f0-9]{3}-?[89ab][a-f0-9]{3}-?[a-f0-9]{12}.*txt', re.I)
    newlist = list(filter(uuid4hex.match, l))  # Read Note below

    # Should be two txt files in the archive (history and the snapshot)
    assert len(newlist) == 2

