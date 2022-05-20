#!/usr/bin/python3

import time
from flask import url_for
from .util import live_server_setup

import json
import uuid


def is_valid_uuid(val):
    try:
        uuid.UUID(str(val))
        return True
    except ValueError:
        return False


def test_api_simple(client, live_server):
    live_server_setup(live_server)

    watch_uuid = None

    res = client.post(
        url_for("createwatch"),
        data=json.dumps({"url": "h://xxxxxxxxxom"}),
        headers={'content-type': 'application/json'},
        follow_redirects=True
    )
    assert res.status_code == 400

    res = client.post(
        url_for("createwatch"),
        data=json.dumps({"url": "https://nice.com"}),
        headers={'content-type': 'application/json'},
        follow_redirects=True
    )
    s = json.loads(res.data)
    assert is_valid_uuid(s['uuid'])
    watch_uuid = s['uuid']

    assert res.status_code == 201

