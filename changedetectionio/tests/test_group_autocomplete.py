#!/usr/bin/env python3
"""The group names offered to the "Group tag" field of a watch as it is typed in (/tags/autocomplete)."""

from flask import url_for

from changedetectionio.blueprint.tags import AUTOCOMPLETE_MAX_RESULTS
from .util import delete_all_watches


def _titles(res):
    return [group['title'] for group in res.json]


def test_group_autocomplete(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config.get('DATASTORE')
    for title in ('Beta', 'Alphabet', 'alpha news', 'The alpha and omega'):
        datastore.add_tag(title=title)
    coloured_uuid = datastore.add_tag(title='Coloured')
    datastore.data['settings']['application']['tags'][coloured_uuid]['tag_colour'] = '#4f8ef7'

    # Any part of the name, any case. Names that start with it first, then by name
    res = client.get(url_for('tags.autocomplete', q='ALPHA'))
    assert res.status_code == 200
    assert _titles(res) == ['alpha news', 'Alphabet', 'The alpha and omega']

    # Nothing typed yet: the groups there are
    assert _titles(client.get(url_for('tags.autocomplete'))) == ['alpha news', 'Alphabet', 'Beta', 'Coloured', 'The alpha and omega']
    assert _titles(client.get(url_for('tags.autocomplete', q='no such group'))) == []

    # Exactly these groups, for colouring the names a field already holds. One that does not exist is left out
    res = client.get(url_for('tags.autocomplete', title=['beta', 'Coloured', 'Not a group']))
    assert _titles(res) == ['Beta', 'Coloured']

    # The colours of the group's label in the watch list: its own colour, or the pair generated from its name
    by_title = {group['title']: group for group in res.json}
    assert by_title['Coloured']['uuid'] == coloured_uuid
    assert by_title['Coloured']['colours']['light']['bg'] == '#4f8ef7'
    assert by_title['Coloured']['colours']['dark']['bg'] == '#4f8ef7'
    assert by_title['Beta']['colours']['light']['bg'] != by_title['Beta']['colours']['dark']['bg']

    # No more than a screenful, typing more narrows it down
    for n in range(AUTOCOMPLETE_MAX_RESULTS + 5):
        datastore.add_tag(title=f"Many {n:02d}")
    assert len(client.get(url_for('tags.autocomplete', q='many')).json) == AUTOCOMPLETE_MAX_RESULTS
    assert _titles(client.get(url_for('tags.autocomplete', q='many 07'))) == ['Many 07']

    datastore.data['settings']['application']['tags'].clear()
    delete_all_watches(client)


def test_group_autocomplete_needs_login_when_password_is_set(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config.get('DATASTORE')
    datastore.add_tag(title='Secret project')
    datastore.data['settings']['application']['password'] = 'not-a-real-hash'
    try:
        res = client.get(url_for('tags.autocomplete', q='secret'))
        assert res.status_code != 200 and b'Secret project' not in res.data
    finally:
        datastore.remove_password()
        datastore.data['settings']['application']['tags'].clear()


def test_group_field_is_marked_for_chips_and_ignores_empty_names(client, live_server, measure_memory_usage, datastore_path):
    """The field is the comma separated text field it always was, with what static/js/tag-chips.js needs on it."""
    datastore = client.application.config.get('DATASTORE')
    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True))

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid),
        # An empty name and the same group twice are not groups of their own
        data={"url": url_for('test_endpoint', _external=True), "tags": "One, , two,one,", "fetch_backend": "html_requests",
              "time_between_check_use_default": "y"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    tags = datastore.data['settings']['application']['tags']
    watch_tags = datastore.data['watching'][uuid]['tags']
    assert [tags[tag_uuid]['title'] for tag_uuid in watch_tags] == ['One', 'two']
    assert len(tags) == 2

    res = client.get(url_for("ui.ui_edit.edit_page", uuid=uuid))
    assert b'value="One, two"' in res.data
    assert b'tag-chips' in res.data
    assert f'data-autocomplete-url="{url_for("tags.autocomplete")}"'.encode() in res.data
    assert b'tag-chips.js' in res.data

    tags.clear()
    delete_all_watches(client)
