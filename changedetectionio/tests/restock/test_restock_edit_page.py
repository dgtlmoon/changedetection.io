#!/usr/bin/env python3
"""
The "Restock & Price Detection" tab (watch edit and group edit) is rendered from real template
files with render_template(), so its help text goes through _() and is extracted for translation (#4612).
"""

from flask import url_for


def test_restock_edit_tab_renders_help_text(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config.get('DATASTORE')
    tag_uuid = datastore.add_tag('restock-group')
    watch_uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True), tag_uuids=[tag_uuid],
                                     extras={'processor': 'restock_diff'})

    res = client.get(url_for("ui.ui_edit.edit_page", uuid=watch_uuid))
    assert res.status_code == 200
    assert b'id="restock-fieldset-price-group"' in res.data
    assert b'Changes in price should trigger a notification' in res.data
    # HTML inside the msgid is kept, not escaped
    assert b'when the price drops <i>below</i> this value' in res.data
    assert b'Note! A Group tag overrides' not in res.data

    # A group tag that overrides the watch shows the note
    datastore.data['settings']['application']['tags'][tag_uuid]['overrides_watch'] = True
    res = client.get(url_for("ui.ui_edit.edit_page", uuid=watch_uuid))
    assert b'Note! A Group tag overrides the restock and price detection here.' in res.data

    # Group edit page carries the override checkbox plus the same restock fields
    res = client.get(url_for("tags.form_tag_edit", uuid=tag_uuid))
    assert res.status_code == 200
    assert b'Used for watches in &#34;Restock &amp; Price detection&#34; mode' in res.data
    assert b'id="restock-fieldset-price-group"' in res.data
    assert b'Changes in price should trigger a notification' in res.data
