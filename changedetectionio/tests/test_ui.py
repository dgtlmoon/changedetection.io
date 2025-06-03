#!/usr/bin/env python3

from flask import url_for
from .util import set_original_response, set_modified_response, live_server_setup, wait_for_all_checks

def test_checkbox_open_diff_in_new_tab(client, live_server):
    
    set_original_response()
   #  live_server_setup(live_server) # Setup on conftest per function

    # Add our URL to the import page
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": url_for('test_endpoint', _external=True)},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data
    wait_for_all_checks(client)

    # Make a change
    set_modified_response()

    # Test case 1 - checkbox is enabled in settings
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-ui-open_diff_in_new_tab": "1"},
        follow_redirects=True
    )
    assert b'Settings updated' in res.data

    # Force recheck
    res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    assert b'Queued 1 watch for rechecking.' in res.data

    wait_for_all_checks(client)
    
    res = client.get(url_for("watchlist.index"))
    lines = res.data.decode().split("\n")

    # Find link to diff page
    target_line = None
    for line in lines:
        if '/diff' in line:
            target_line = line.strip()
            break

    assert target_line != None
    assert 'target=' in target_line

    # Test case 2 - checkbox is disabled in settings
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-ui-open_diff_in_new_tab": ""},
        follow_redirects=True
    )
    assert b'Settings updated' in res.data

    # Force recheck
    res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    assert b'Queued 1 watch for rechecking.' in res.data

    wait_for_all_checks(client)
    
    res = client.get(url_for("watchlist.index"))
    lines = res.data.decode().split("\n")

    # Find link to diff page
    target_line = None
    for line in lines:
        if '/diff' in line:
            target_line = line.strip()
            break

    assert target_line != None
    assert 'target=' not in target_line

    # Cleanup everything
    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data
