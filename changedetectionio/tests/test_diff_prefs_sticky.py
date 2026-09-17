"""The history page remembers the display filters it was last used with.

Preferences are saved on the watch, not in the browser, so a filter chosen on the
desktop is honoured when the same watch's history is opened on a phone. See #3381.
"""

import json
from flask import url_for
from bs4 import BeautifulSoup


# Line two changes, lines one and three do not - so "alpha" is present only while
# unchanged lines are being included, which makes it a read of the actual diff output
# rather than of the checkbox that asked for it.
FIRST_VERSION = "alpha\nbravo\ncharlie"
SECOND_VERSION = "alpha\nbravo\ndelta"

# changesOnly is absent, which the form treats as "unticked" - so this submission turns
# off the inclusion of unchanged lines and switches to word diffing.
SUBMITTED_PREFS = 'type=diffWords&ignoreWhitespace=on&removed=on&added=on&replaced=on'


def add_watch_with_history(client, url='https://example.com/releases'):
    datastore = client.application.config['DATASTORE']
    uuid = datastore.add_watch(url=url, extras={'paused': True})
    watch = datastore.data['watching'][uuid]
    watch.save_history_blob(FIRST_VERSION, 1700000000, 'first')
    watch.save_history_blob(SECOND_VERSION, 1700000060, 'second')
    return uuid, watch


def get_diff_page(test_client, uuid, query_string=None):
    url = url_for('ui.ui_diff.diff_history_page', uuid=uuid)
    if query_string:
        url = f"{url}?{query_string}"
    response = test_client.get(url)
    assert response.status_code == 200
    return BeautifulSoup(response.data, 'html.parser')


def is_checked(page, element_id):
    element = page.select_one(f"#{element_id}")
    assert element is not None, f"#{element_id} is missing from the diff form"
    return element.has_attr('checked')


def assert_renders_defaults(page):
    """The state of the form, and of the diff itself, with nothing saved."""
    assert is_checked(page, 'changesOnly')
    assert is_checked(page, 'diffLines')
    assert not is_checked(page, 'diffWords')
    assert not is_checked(page, 'ignoreWhitespace')
    assert 'alpha' in page.select_one('#difference').get_text()


def assert_renders_submitted_prefs(page):
    """The same two reads after SUBMITTED_PREFS was applied to this watch."""
    assert not is_checked(page, 'changesOnly')
    assert is_checked(page, 'diffWords')
    assert not is_checked(page, 'diffLines')
    assert is_checked(page, 'ignoreWhitespace')
    # Unchanged lines are gone from the rendered diff, not merely from the checkbox.
    assert 'alpha' not in page.select_one('#difference').get_text()
    assert 'delta' in page.select_one('#difference').get_text()


def test_diff_page_renders_defaults_when_nothing_is_saved(client):
    """Control for every test below: a watch nobody has set filters on."""
    uuid, watch = add_watch_with_history(client)
    assert watch.get('diff_display_prefs') is None
    assert_renders_defaults(get_diff_page(client, uuid))


def test_submitted_prefs_are_applied_to_the_next_plain_visit(client):
    uuid, watch = add_watch_with_history(client)

    assert_renders_submitted_prefs(get_diff_page(client, uuid, SUBMITTED_PREFS))

    saved = watch.get('diff_display_prefs')
    assert saved == {
        'changesOnly': False,
        'ignoreWhitespace': True,
        'removed': True,
        'added': True,
        'replaced': True,
        'type': 'diffWords',
        'llm_all_changes': False,
    }

    # The load that matters - no query string at all.
    assert_renders_submitted_prefs(get_diff_page(client, uuid))


def test_saved_prefs_follow_the_watch_not_the_browser(client):
    """The point of storing this on the watch: set it on one device, see it on another.

    A second client has its own cookie jar and session, so it stands in for the phone
    opening the history page the desktop just configured.
    """
    uuid, watch = add_watch_with_history(client)
    get_diff_page(client, uuid, SUBMITTED_PREFS)

    other_device = client.application.test_client()
    assert_renders_submitted_prefs(get_diff_page(other_device, uuid))


def test_saved_prefs_are_per_watch(client):
    configured_uuid, _ = add_watch_with_history(client, url='https://example.com/configured')
    untouched_uuid, untouched = add_watch_with_history(client, url='https://example.com/untouched')

    get_diff_page(client, configured_uuid, SUBMITTED_PREFS)

    assert untouched.get('diff_display_prefs') is None
    assert_renders_defaults(get_diff_page(client, untouched_uuid))


def test_unchanged_prefs_are_not_rewritten(client):
    """Every filter click re-renders the page; only a real change should hit the disk."""
    uuid, watch = add_watch_with_history(client)

    get_diff_page(client, uuid, SUBMITTED_PREFS)
    saved = watch.get('diff_display_prefs')

    get_diff_page(client, uuid, SUBMITTED_PREFS)
    assert watch.get('diff_display_prefs') is saved, \
        "Re-submitting identical preferences should not replace the stored dict"


def test_corrupt_saved_prefs_fall_back_to_defaults(client):
    """Saved values are data on disk, so a wrong type must degrade, never 500."""
    uuid, watch = add_watch_with_history(client)

    watch['diff_display_prefs'] = {
        'type': 'junk',            # not a diff type we know
        'changesOnly': 'yes',      # a string, not a bool
        'added': 1,                # truthy, but not a bool
        'ignoreWhitespace': True,  # valid, and must still be honoured
    }
    page = get_diff_page(client, uuid)
    assert is_checked(page, 'diffLines')
    assert is_checked(page, 'changesOnly')
    assert is_checked(page, 'added')
    assert is_checked(page, 'ignoreWhitespace'), \
        "A valid key must still apply even when a neighbouring key is junk"
    assert 'alpha' in page.select_one('#difference').get_text()

    # Not a dict at all - e.g. hand-edited watch.json
    watch['diff_display_prefs'] = 'not-a-dict'
    assert_renders_defaults(get_diff_page(client, uuid))


def test_saving_prefs_does_not_mark_the_watch_as_edited(client):
    """An edited watch skips the unchanged-content shortcut on its next check.

    Viewing a diff must not cost a full reprocess, which is why the key is listed in
    SYSTEM_MANAGED_NON_SPEC_FIELDS.
    """
    uuid, watch = add_watch_with_history(client)
    watch.reset_watch_edited_flag()
    assert watch.was_edited is False

    get_diff_page(client, uuid, SUBMITTED_PREFS)
    assert watch.get('diff_display_prefs'), "precondition: the submission was saved"
    assert watch.was_edited is False

    # Control: the flag is reachable and does still fire for an ordinary field, so the
    # assertion above is the exemption working rather than a flag that never sets.
    watch['title'] = 'renamed'
    assert watch.was_edited is True


def test_saved_prefs_stay_off_the_api(client):
    """The key is internal: stripped from GET, discarded on PUT, so GET -> PUT still works."""
    uuid, watch = add_watch_with_history(client)
    get_diff_page(client, uuid, SUBMITTED_PREFS)
    saved = watch.get('diff_display_prefs')
    assert saved

    datastore = client.application.config['DATASTORE']
    api_key = datastore.data['settings']['application'].get('api_access_token')

    res = client.get(url_for("watch", uuid=uuid), headers={'x-api-key': api_key})
    assert res.status_code == 200
    assert 'diff_display_prefs' not in res.json

    payload = dict(res.json)
    payload['diff_display_prefs'] = {'type': 'diffLines'}  # a client could still send it
    res = client.put(
        url_for("watch", uuid=uuid),
        headers={'x-api-key': api_key, 'content-type': 'application/json'},
        data=json.dumps(payload),
    )
    assert res.status_code == 200, \
        f"PUT round-tripping the GET response should succeed (got {res.status_code}: {res.data!r})"
    assert watch.get('diff_display_prefs') == saved, \
        "The API must not be able to overwrite the saved preferences"
