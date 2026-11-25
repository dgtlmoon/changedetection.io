#!/usr/bin/env python3
"""The "Group" action of the watch list: the selected watches are added to the groups named in the modal's
chips field (the same field as a watch's "Group tag"), comma separated on the way to the server."""

from flask import url_for

from .util import delete_all_watches


def _apply(client, uuids, names, remove_existing=False):
    return client.post(
        url_for("ui.form_watch_list_checkbox_operations"),
        data={"op": "assign-tag-replace" if remove_existing else "assign-tag", "uuids": uuids, "op_extradata": names},
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
    # "Also remove any existing group assigned": there, not ticked, with an operation of its own
    import re
    checkbox = re.search(rb'<input[^>]*name="bulk_groups_replace"[^>]*>', res.data).group(0)
    assert b'type="checkbox"' in checkbox and b'checked' not in checkbox
    assert b'Also remove any existing group assigned' in res.data
    assert b'name="op" value="assign-tag-replace" id="op-assign-tag-replace" hidden' in res.data

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


def test_group_action_can_remove_the_groups_the_watches_were_in(client, live_server, measure_memory_usage, datastore_path):
    """"Also remove any existing group assigned": the groups named take the place of the ones a watch is in."""
    datastore = client.application.config.get('DATASTORE')
    tags = datastore.data['settings']['application']['tags']
    old_a, old_b, kept = datastore.add_tag(title='Old A'), datastore.add_tag(title='Old B'), datastore.add_tag(title='Kept')
    one = datastore.add_watch(url=url_for('test_endpoint', _external=True), extras={'paused': True})
    two = datastore.add_watch(url=url_for('test_endpoint', _external=True) + '?2', extras={'paused': True})
    untouched = datastore.add_watch(url=url_for('test_endpoint', _external=True) + '?3', extras={'paused': True})
    datastore.data['watching'][one]['tags'] = [old_a, kept]
    datastore.data['watching'][two]['tags'] = [old_b]
    datastore.data['watching'][untouched]['tags'] = [old_a]

    # Not ticked: added to what they are in, as before
    _apply(client, [one], "Kept, Fresh")
    fresh = next(uuid for uuid, tag in tags.items() if tag['title'] == 'Fresh')
    assert datastore.data['watching'][one]['tags'] == [old_a, kept, fresh]

    # Ticked: only the groups named, for the watches that were selected
    res = _apply(client, [one, two], "kept, Fresh", remove_existing=True)
    assert b"2 watches were tagged" in res.data
    assert datastore.data['watching'][one]['tags'] == [kept, fresh]
    assert datastore.data['watching'][two]['tags'] == [kept, fresh]
    assert datastore.data['watching'][untouched]['tags'] == [old_a], "Not selected, not touched"
    # The groups themselves are still there, only these watches left them
    assert sorted(tag['title'] for tag in tags.values()) == ['Fresh', 'Kept', 'Old A', 'Old B']

    # Ticked with no group named: nothing is removed, it is not a way to empty a watch's groups by accident
    for names in ("", " , ,"):
        res = _apply(client, [one, two], names, remove_existing=True)
        assert b"No group name given" in res.data
        assert datastore.data['watching'][one]['tags'] == [kept, fresh]
        assert datastore.data['watching'][two]['tags'] == [kept, fresh]

    tags.clear()
    delete_all_watches(client)
