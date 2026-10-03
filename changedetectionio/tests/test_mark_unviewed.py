#!/usr/bin/env python3

"""Re #4382 - the watch list "Mark unviewed" bulk operation.

Mark unviewed winds last_viewed back to the second-newest snapshot, so the row is unviewed again
and the [diff] link still opens on the latest change. A watch with only one snapshot has no
change to un-view, so it must be left alone.
"""

from flask import url_for

from .util import set_original_response, set_modified_response, wait_for_all_checks, delete_all_watches, \
    extract_UUID_from_client


def test_mark_unviewed(client, live_server, measure_memory_usage, datastore_path):
    set_original_response(datastore_path=datastore_path)
    datastore = live_server.app.config['DATASTORE']

    client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": url_for('test_endpoint', _external=True), "tags": ''},
        follow_redirects=True
    )
    wait_for_all_checks(client)
    uuid = extract_UUID_from_client(client)
    watch = datastore.data['watching'][uuid]

    # Only one snapshot - nothing to un-view, so the operation must not flag the row
    res = client.post(url_for("ui.form_watch_list_checkbox_operations"),
                      data={"op": "mark-unviewed", "uuids": uuid},
                      follow_redirects=True)
    assert b'0 watches updated' in res.data
    assert not watch.has_unviewed
    assert b'has-unread-changes' not in res.data

    # A real change lands -> unviewed
    set_modified_response(datastore_path=datastore_path)
    client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    assert watch.has_unviewed

    res = client.post(url_for("ui.form_watch_list_checkbox_operations"),
                      data={"op": "mark-viewed", "uuids": uuid},
                      follow_redirects=True)
    assert not watch.has_unviewed
    assert b'has-unread-changes' not in res.data

    # The actual feature - it comes back as unviewed
    res = client.post(url_for("ui.form_watch_list_checkbox_operations"),
                      data={"op": "mark-unviewed", "uuids": uuid},
                      follow_redirects=True)
    assert b'1 watches updated' in res.data
    assert watch.has_unviewed
    assert b'has-unread-changes' in res.data

    # ...and [diff] still opens on the latest change, not the whole history
    sorted_keys = sorted(watch.history.keys(), key=lambda x: int(x))
    assert watch.get_from_version_based_on_last_viewed == sorted_keys[-2]

    delete_all_watches(client)
