#!/usr/bin/env python3
"""The "Group tag" field of a watch (StringTagUUIDAutocompleteChip in forms.py): the text field of comma separated
group names it always was, with every group there is next to it in a <datalist> for static/js/tag-chips.js (and
for the browser's own suggestions without the script). The chips themselves are tested in tests/UI/puppeteer."""

import html
import json
import re

from flask import url_for

from .util import delete_all_watches


def _datalist_groups(res):
    """{title: colours} of the <datalist> the field is rendered with"""
    datalist = re.search(rb'<datalist id="tags-groups">(.*?)</datalist>', res.data, re.S)
    assert datalist, "The field comes with a datalist of the groups"
    options = re.findall(r'<option value="([^"]*)" data-colours="([^"]*)"></option>', datalist.group(1).decode())
    return {html.unescape(title): json.loads(html.unescape(colours)) for title, colours in options}


def test_group_field_lists_every_group(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config.get('DATASTORE')
    tags = datastore.data['settings']['application']['tags']
    for title in ('Beta', 'alpha news', 'Alphabet'):
        datastore.add_tag(title=title)
    coloured_uuid = datastore.add_tag(title='Coloured')
    tags[coloured_uuid]['tag_colour'] = '#4f8ef7'
    # A name is text wherever it is put
    hostile_title = '"><script>alert(1)</script> & \'co\''
    datastore.add_tag(title=hostile_title)
    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True), tag='Beta, Coloured')

    res = client.get(url_for("ui.ui_edit.edit_page", uuid=uuid))
    assert res.status_code == 200

    # The plain field, pointed at the datalist, with the script for the chips
    field = re.search(rb'<input[^>]*name="tags"[^>]*>', res.data).group(0)
    assert b'type="text"' in field
    # (a watch's groups are not kept in the order they were given)
    assert sorted(re.search(rb'value="([^"]*)"', field).group(1).decode().split(', ')) == ['Beta', 'Coloured']
    assert b'list="tags-groups"' in field and b'tag-chips' in field
    assert res.data.count(b'tag-chips.js') == 1
    assert b'<script>alert(1)</script>' not in res.data

    groups = _datalist_groups(res)
    assert list(groups) == [hostile_title, 'alpha news', 'Alphabet', 'Beta', 'Coloured'], "Every group, by name"

    # The colours of the group's label in the watch list: its own colour, or the pair generated from its name
    assert groups['Coloured']['light']['bg'] == groups['Coloured']['dark']['bg'] == '#4f8ef7'
    assert groups['Beta']['light']['bg'] != groups['Beta']['dark']['bg']

    tags.clear()
    delete_all_watches(client)


def test_group_field_ignores_empty_names(client, live_server, measure_memory_usage, datastore_path):
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

    tags.clear()
    delete_all_watches(client)


def test_group_field_keeps_its_names_when_the_save_fails(client, live_server, measure_memory_usage, datastore_path):
    """Another field has an error: the form comes back with the groups that were sent. It came back with the word
    "error" in their place, and saving the corrected form then put the watch in one group called "error"."""
    datastore = client.application.config.get('DATASTORE')
    tags = datastore.data['settings']['application']['tags']
    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True), tag='Before')
    before = list(datastore.data['watching'][uuid]['tags'])

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid),
        data={"url": "not a url", "tags": " One,two ,, Three & <b>four</b>,", "fetch_backend": "html_requests",
              "time_between_check_use_default": "y"},
        follow_redirects=True
    )
    assert b"Updated watch." not in res.data and b"invalid URL" in res.data

    field = re.search(rb'<input[^>]*name="tags"[^>]*>', res.data).group(0).decode()
    assert html.unescape(re.search(r'value="([^"]*)"', field).group(1)) == 'One, two, Three & <b>four</b>'
    assert 'value="error"' not in field
    assert '<b>four</b>' not in field, "As text, not as markup"

    # Nothing was saved, and no groups were made for a save that did not happen
    assert datastore.data['watching'][uuid]['tags'] == before
    assert sorted(tag['title'] for tag in tags.values()) == ['Before']

    # The same in the form that adds a watch
    res = client.post(url_for("ui.ui_views.form_quick_watch_add"), data={"url": "not a url", "tags": "Quick one, Quick two"},
                      follow_redirects=True)
    assert b"Watch added" not in res.data
    assert sorted(tag['title'] for tag in tags.values()) == ['Before']

    tags.clear()
    delete_all_watches(client)


def test_split_group_names():
    from changedetectionio.model.Tag import split_group_names

    assert split_group_names(' One,two ,, ,Three,') == ['One', 'two', 'Three']
    assert split_group_names('') == [] and split_group_names(None) == []
    # A group that has a comma in its name from before is kept whole, however it is spaced or capitalised
    titles = ['Sales, EU', 'Sales', 'A, B, C', 'A, B']
    assert split_group_names('Other, Sales, EU, Sales', titles) == ['Other', 'Sales, EU', 'Sales']
    assert split_group_names('sales ,eu', titles) == ['Sales, EU']
    assert split_group_names('A, B, C, A, B, A', titles) == ['A, B, C', 'A, B', 'A'], "The longest name first"
    assert split_group_names('Sales, EUROPE', titles) == ['Sales', 'EUROPE']


def test_group_name_cannot_have_a_comma(client, live_server, measure_memory_usage, datastore_path):
    """Several groups are written with commas between them, so a name with a comma in it cannot be told from two
    groups: saving a watch that was in "Sales, EU" moved it into new groups "Sales" and "EU"."""
    import json as json_lib
    datastore = client.application.config.get('DATASTORE')
    tags = datastore.data['settings']['application']['tags']
    api_key = datastore.data['settings']['application'].get('api_access_token')
    api_headers = {'content-type': 'application/json', 'x-api-key': api_key}
    titles = lambda: sorted(tag['title'] for tag in tags.values())

    # Not as a new name: the groups page, the API
    res = client.post(url_for("tags.form_tag_add"), data={"name": "Sales, EU"}, follow_redirects=True)
    assert b"cannot have a comma" in res.data and titles() == []
    res = client.post(url_for("tag"), data=json_lib.dumps({"title": "Sales, EU"}), headers=api_headers)
    assert res.status_code == 400 and b"comma" in res.data and titles() == []

    # Not as a new name for a group there is: its edit page, the API
    plain_uuid = datastore.add_tag(title='Plain')
    res = client.post(url_for("tags.form_tag_edit_submit", uuid=plain_uuid), data={"title": "Plain, renamed"}, follow_redirects=True)
    assert b"cannot have a comma" in res.data and titles() == ['Plain']
    res = client.put(url_for("tag", uuid=plain_uuid), data=json_lib.dumps({"title": "Plain, renamed"}), headers=api_headers)
    assert res.status_code == 400 and titles() == ['Plain']

    # A group that has one from before keeps working: saved with its name as it is, by its page and the API
    old_uuid = datastore.add_tag(title='Sales, EU')
    res = client.post(url_for("tags.form_tag_edit_submit", uuid=old_uuid), data={"title": "Sales, EU", "url_match_pattern": "*sales*"},
                      follow_redirects=True)
    assert b"cannot have a comma" not in res.data and tags[old_uuid]['url_match_pattern'] == '*sales*'
    res = client.put(url_for("tag", uuid=old_uuid), data=json_lib.dumps({"title": "Sales, EU", "notification_muted": True}), headers=api_headers)
    assert res.status_code == 200

    # And a watch in it stays in it. Its edit page saved as it was shown:
    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True), tag_uuids=[old_uuid, plain_uuid])
    res = client.get(url_for("ui.ui_edit.edit_page", uuid=uuid))
    shown = html.unescape(re.search(r'value="([^"]*)"', re.search(rb'<input[^>]*name="tags"[^>]*>', res.data).group(0).decode()).group(1))
    assert sorted(shown.split(', ')) == ['EU', 'Plain', 'Sales'] or 'Sales, EU' in shown
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid),
        data={"url": url_for('test_endpoint', _external=True), "tags": shown, "fetch_backend": "html_requests", "time_between_check_use_default": "y"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    assert sorted(datastore.data['watching'][uuid]['tags']) == sorted([old_uuid, plain_uuid])
    assert titles() == ['Plain', 'Sales, EU'], 'No new groups "Sales" and "EU"'

    # The "Group" action of the watch list, and a watch added with its groups as a text
    other = datastore.add_watch(url=url_for('test_endpoint', _external=True))
    client.post(url_for("ui.form_watch_list_checkbox_operations"), data={"op": "assign-tag", "op_extradata": "sales,eu, Plain", "uuids": [other]},
                follow_redirects=True)
    assert sorted(datastore.data['watching'][other]['tags']) == sorted([old_uuid, plain_uuid])
    third = datastore.add_watch(url=url_for('test_endpoint', _external=True), tag='Sales, EU')
    assert datastore.data['watching'][third]['tags'] == [old_uuid]
    assert titles() == ['Plain', 'Sales, EU']

    tags.clear()
    delete_all_watches(client)
