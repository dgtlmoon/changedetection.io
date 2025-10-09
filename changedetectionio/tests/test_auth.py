#!/usr/bin/env python3

import time
from flask import url_for
from .util import live_server_setup, wait_for_all_checks

# test pages with http://username@password:foobar.com/ work
def test_basic_auth(client, live_server, measure_memory_usage):
   #  live_server_setup(live_server) # Setup on conftest per function


    # This page will echo back any auth info
    test_url = url_for('test_basicauth_method', _external=True).replace("//","//myuser:mypass@")
    time.sleep(1)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    time.sleep(1)
    # Check form validation
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={"include_filters": "", "url": test_url, "tags": "", "headers": "", 'fetch_backend': "html_requests", "time_between_check_use_default": "y"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    wait_for_all_checks(client)
    res = client.get(
        url_for("ui.ui_views.preview_page", uuid="first"),
        follow_redirects=True
    )

    assert b'myuser mypass basic' in res.data
