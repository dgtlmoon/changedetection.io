#!/usr/bin/env python3
"""The "Group" action of the watch list: the selected watches are added to the groups named in the modal's
chips field (the same field as a watch's "Group tag"), comma separated on the way to the server."""

from flask import url_for

from .util import delete_all_watches


def _apply(client, uuids, names):
    return client.post(
        url_for("ui.form_watch_list_checkbox_operations"),
        data={"op": "assign-tag", "uuids": uuids, "op_extradata": names},
        follow_redirects=True,
    )


def test_group_action_is_a_modal_with_the_chips_field(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config.get('DATASTORE')
    datastore.add_tag(title='Shops <b>')
    datastore.add_watch(url=url_for('test_endpoint', _external=True), extras={'paused': True})

    res = client.get(url_for("watchlist.index"))
    # A button that opens the modal, the operation itself is the hidden button the modal fires
    assert b'type="button" class="pure-button button-secondary button-xsmall" id="checkbox-assign-tag"' in res.data
    assert b'name="op" value="assign-tag" id="op-assign-tag" hidden' in res.data
    # The modal's content: the chips field with the groups there are to suggest
    assert b'<template id="bulk-group-options">' in res.data
    assert b'name="bulk_groups"' in res.data and b'tag-chips' in res.data
    assert b'<option value="Shops &lt;b&gt;"' in res.data
    assert b'prompt(' not in res.data

    datastore.data['settings']['application']['tags'].clear()
    delete_all_watches(client)


def test_group_action_adds_the_watches_to_every_group_named(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config.get('DATASTORE')
    existing = datastore.add_tag(title='Shops')
    one = datastore.add_watch(url=url_for('test_endpoint', _external=True), extras={'paused': True})
    two = datastore.add_watch(url=url_for('test_endpoint', _external=True) + '?2', extras={'paused': True})
    untouched = datastore.add_watch(url=url_for('test_endpoint', _external=True) + '?3', extras={'paused': True})
    datastore.data['watching'][one]['tags'] = [existing]

    # An existing group (any case) and one that is new
    res = _apply(client, [one, two], "shops,  Weekly reports ,")
    assert b"2 watches were tagged" in res.data

    tags = datastore.data['settings']['application']['tags']
    assert sorted(tag['title'] for tag in tags.values()) == ['Shops', 'Weekly reports'], "No second 'shops'"
    weekly = next(uuid for uuid, tag in tags.items() if tag['title'] == 'Weekly reports')

    assert datastore.data['watching'][one]['tags'] == [existing, weekly], "Already in Shops, not added twice"
    assert datastore.data['watching'][two]['tags'] == [existing, weekly]
    assert datastore.data['watching'][untouched]['tags'] == []

    # The same again changes nothing
    _apply(client, [one, two], "Shops, Weekly reports")
    assert datastore.data['watching'][one]['tags'] == [existing, weekly]

    tags.clear()
    delete_all_watches(client)


def test_group_action_without_a_name_does_nothing(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config.get('DATASTORE')
    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True), extras={'paused': True})

    for nothing in ("", " , ", "null"[:0]):
        res = _apply(client, [uuid], nothing)
        assert b"watches were tagged" not in res.data, "Nothing was tagged, so it does not say so"
        assert b"No group name given" in res.data

    assert datastore.data['watching'][uuid]['tags'] == []
    assert not datastore.data['settings']['application']['tags']

    delete_all_watches(client)
