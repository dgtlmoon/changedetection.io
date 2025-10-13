#!/usr/bin/env python3

import time
from flask import url_for
from urllib.request import urlopen
from .util import set_original_response, set_modified_response, live_server_setup, delete_all_watches
import re

sleep_time_for_fetch_thread = 3


def test_share_watch(client, live_server, measure_memory_usage):
    set_original_response()
   #  live_server_setup(live_server) # Setup on conftest per function

    test_url = url_for('test_endpoint', _external=True)
    include_filters = ".nice-filter"

    # Add our URL to the import page
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    # Goto the edit page, add our ignore text
    # Add our URL to the import page
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={"include_filters": include_filters, "url": test_url, "tags": "", "headers": "", 'fetch_backend': "html_requests", "time_between_check_use_default": "y"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    # Check it saved
    res = client.get(
        url_for("ui.ui_edit.edit_page", uuid="first"),
    )
    assert bytes(include_filters.encode('utf-8')) in res.data

    # click share the link
    res = client.get(
        url_for("ui.form_share_put_watch", uuid="first"),
        follow_redirects=True
    )

    assert b"Share this link:" in res.data
    assert b"https://changedetection.io/share/" in res.data

    html = res.data.decode()
    share_link_search = re.search('<span id="share-link">(.*)</span>', html, re.IGNORECASE)
    assert share_link_search

    # Now delete what we have, we will try to re-import it
    # Cleanup everything
    delete_all_watches(client)

    # Add our URL to the import page
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": share_link_search.group(1)},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data

    # Now hit edit, we should see what we expect
    # that the import fetched the meta-data

    # Check it saved
    res = client.get(
        url_for("ui.ui_edit.edit_page", uuid="first"),
    )
    assert bytes(include_filters.encode('utf-8')) in res.data

    # Check it saved the URL
    res = client.get(url_for("watchlist.index"))
    assert bytes(test_url.encode('utf-8')) in res.data
