#!/usr/bin/python3

import time
from flask import url_for
from .util import live_server_setup


# If there was only a change in the whitespacing, then we shouldnt have a change detected
def test_jinja2_in_url_query(client, live_server):
    live_server_setup(live_server)

    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URL to the import page
    test_url = url_for('test_return_query', _external=True)

    # because url_for() will URL-encode the var, but we dont here
    full_url = "{}?{}".format(test_url,
                              "date={% now 'Europe/Berlin', '%Y' %}.{% now 'Europe/Berlin', '%m' %}.{% now 'Europe/Berlin', '%d' %}", )
    res = client.post(
        url_for("form_quick_watch_add"),
        data={"url": full_url, "tag": "test"},
        follow_redirects=True
    )
    assert b"Watch added" in res.data
    time.sleep(3)
    # It should report nothing found (no new 'unviewed' class)
    res = client.get(
        url_for("preview_page", uuid="first"),
        follow_redirects=True
    )
    assert b'date=2' in res.data
