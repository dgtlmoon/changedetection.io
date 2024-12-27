#!/usr/bin/env python3

from .util import set_original_response, live_server_setup, wait_for_all_checks
from flask import url_for
import io
from zipfile import ZipFile
import re
import time


def test_backup(client, live_server, measure_memory_usage):
    live_server_setup(live_server)

    set_original_response()

    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URL to the import page
    res = client.post(
        url_for("import_page"),
        data={"urls": url_for('test_endpoint', _external=True)+"?somechar=őőőőőőőő"},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data
    wait_for_all_checks(client)

    # Launch the thread in the background to create the backup
    res = client.get(
        url_for("backups.request_backup"),
        follow_redirects=True
    )
    time.sleep(2)

    res = client.get(
        url_for("backups.index"),
        follow_redirects=True
    )
    # Can see the download link to the backup
    assert b'<a href="/backups/download/changedetection-backup-20' in res.data
    assert b'Remove backups' in res.data

    # Get the latest one
    res = client.get(
        url_for("backups.download_backup", filename="latest"),
        follow_redirects=True
    )

    # Should get the right zip content type
    assert res.content_type == "application/zip"

    # Should be PK/ZIP stream
    assert res.data.count(b'PK') >= 2

    backup = ZipFile(io.BytesIO(res.data))
    l = backup.namelist()
    uuid4hex = re.compile('^[a-f0-9]{8}-?[a-f0-9]{4}-?4[a-f0-9]{3}-?[89ab][a-f0-9]{3}-?[a-f0-9]{12}.*txt', re.I)
    newlist = list(filter(uuid4hex.match, l))  # Read Note below

    # Should be two txt files in the archive (history and the snapshot)
    assert len(newlist) == 2

    # Get the latest one
    res = client.get(
        url_for("backups.remove_backups"),
        follow_redirects=True
    )

    assert b'No backups found.' in res.data