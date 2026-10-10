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

# The opposite of SUBMITTED_PREFS on every key that differs, so a write by a requester who
# should not be able to write is loud rather than coincidentally equal.
OTHER_PREFS = 'type=diffLines&changesOnly=on&removed=on&added=on&replaced=on'

SHARED_INSTANCE_PASSWORD = 'foobar'


def add_watch_with_history(client, url='https://example.com/releases'):
    datastore = client.application.config['DATASTORE']
    uuid = datastore.add_watch(url=url, extras={'paused': True})
    watch = datastore.data['watching'][uuid]
    watch.save_history_blob(FIRST_VERSION, 1700000000, 'first')
    watch.save_history_blob(SECOND_VERSION, 1700000060, 'second')
    return uuid, watch


def configure_llm(client):
    """The AI checkbox only renders on an instance with a model configured."""
    datastore = client.application.config['DATASTORE']
    datastore.data['settings']['application']['llm'] = {'model': 'gpt-4o-mini', 'api_key': 'sk-test'}


def enable_password_protected_sharing(client):
    """Password on, `shared_diff_access` on - the setup the auth exemption exists for.

    Posting the real settings form rather than poking the datastore, so the stored password
    is a hash the login route will actually accept.
    """
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-password": SHARED_INSTANCE_PASSWORD,
              "application-shared_diff_access": "True",
              "requests-time_between_check-minutes": 180,
              "application-fetch_backend": "html_requests"},
        follow_redirects=True,
    )
    assert b"Password protection enabled." in res.data


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


def test_the_ai_checkbox_is_not_remembered(client):
    """The style filters stick; the AI toggle deliberately does not.

    A remembered tick would ask for a wider - and billable - summary on every later change
    pair without anyone asking for it again, so it resets on each visit.
    """
    configure_llm(client)
    uuid, watch = add_watch_with_history(client)

    page = get_diff_page(client, uuid, f"{SUBMITTED_PREFS}&llm_all_changes=on")
    assert is_checked(page, 'llm_all_changes'),         "precondition: the submission itself still honours the tick"
    assert 'llm_all_changes' not in watch.get('diff_display_prefs')

    page = get_diff_page(client, uuid)
    assert not is_checked(page, 'llm_all_changes')
    # The style filters from that same submission did stick, so this is the exclusion
    # working rather than the whole submission having been dropped.
    assert is_checked(page, 'diffWords')
    assert is_checked(page, 'ignoreWhitespace')

    # Nor can a stored value resurrect it - the read side skips it too.
    watch['diff_display_prefs'] = {'llm_all_changes': True, 'ignoreWhitespace': True}
    page = get_diff_page(client, uuid)
    assert not is_checked(page, 'llm_all_changes')
    assert is_checked(page, 'ignoreWhitespace')


def test_an_anonymous_shared_diff_viewer_cannot_change_what_the_watch_remembers(client):
    """`shared_diff_access` makes this page readable without a login, and read-only.

    Anyone holding a shared history link could otherwise decide the filters the operator
    sees on their next visit, and force a watch commit per request. Their filters still
    apply to the page they asked for - they are just not remembered.
    """
    uuid, watch = add_watch_with_history(client)
    get_diff_page(client, uuid, SUBMITTED_PREFS)
    operators_prefs = watch.get('diff_display_prefs')
    assert operators_prefs, "precondition: a submission from the operator is saved"

    enable_password_protected_sharing(client)

    stranger = client.application.test_client()
    page = get_diff_page(stranger, uuid, OTHER_PREFS)
    # The page they asked for is the page they get - this is a 200 with the diff on it, so
    # the auth exemption is genuinely in force and the assertion below is not vacuous.
    assert is_checked(page, 'diffLines')
    assert is_checked(page, 'changesOnly')

    assert watch.get('diff_display_prefs') == operators_prefs, \
        "An anonymous shared-diff viewer must not write preferences onto the watch"
    # Reading stays shared: their plain visit still shows the operator's choices.
    assert_renders_submitted_prefs(get_diff_page(stranger, uuid))

    # Control: the guard is about being anonymous, not about a password being configured.
    # Logging in on the same instance restores saving, so the assertion above is the
    # authorisation check working rather than saving being switched off wholesale.
    operator = client.application.test_client()
    res = operator.post(url_for("login"), data={"password": SHARED_INSTANCE_PASSWORD},
                        follow_redirects=True)
    assert b"/logout" in res.data, "precondition: the control client really is logged in"

    get_diff_page(operator, uuid, OTHER_PREFS)
    assert watch.get('diff_display_prefs') != operators_prefs
    assert watch.get('diff_display_prefs')['type'] == 'diffLines'


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
