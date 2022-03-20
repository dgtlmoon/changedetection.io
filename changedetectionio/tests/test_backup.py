#!/usr/bin/python3

import time
from flask import url_for
from urllib.request import urlopen
from . util import set_original_response, set_modified_response, live_server_setup


def test_backup(client, live_server):

    live_server_setup(live_server)

    # Give the endpoint time to spin up
    time.sleep(1)

    res = client.get(
        url_for("get_backup"),
        follow_redirects=True
    )

    # Should get the right zip content type
    assert res.content_type == "application/zip"
    # Should be PK/ZIP stream
    assert res.data.count(b'PK') >= 2

