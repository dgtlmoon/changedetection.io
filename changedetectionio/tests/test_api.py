#!/usr/bin/python3

import time
from flask import url_for
from . util import live_server_setup


def test_api_simple(client, live_server):
    live_server_setup(live_server)

    res = client.post(
        url_for("createwatch"),
        data={"url": "https://nice.com"},
        headers={'content-type': 'application/json'},
        follow_redirects=True
    )
    assert len(res.data) >= 20
    assert res.status_code == 201

    # try invalid url

    #assert res.status_code == 400

