#!/usr/bin/python3

import time
from flask import url_for
from .util import set_original_response, set_modified_response, live_server_setup, wait_for_all_checks, extract_rss_token_from_UI


def test_rss_and_token(client, live_server):
    set_original_response()
    live_server_setup(live_server)

    # Add our URL to the import page
    res = client.post(
        url_for("import_page"),
        data={"urls": url_for('test_random_content_endpoint', _external=True)},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data
    rss_token = extract_rss_token_from_UI(client)

    wait_for_all_checks(client)
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Add our URL to the import page
    res = client.get(
        url_for("rss", token="bad token", _external=True),
        follow_redirects=True
    )

    assert b"Access denied, bad token" in res.data

    res = client.get(
        url_for("rss", token=rss_token, _external=True),
        follow_redirects=True
    )
    assert b"Access denied, bad token" not in res.data
    assert b"Random content" in res.data
