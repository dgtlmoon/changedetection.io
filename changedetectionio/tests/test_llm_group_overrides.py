#!/usr/bin/env python3
"""
Tests for the AI/LLM settings a group hands to its watches.

A group has exactly ONE AI control on its edit page — the ternary llm_backend_profile
("AI for watches in this group"):

  On                   the group's llm_intent / llm_change_summary apply to every watch in
                       it (unless the watch fills in its own), and AI is on for all of them
  Off                  AI off for every watch in the group; its prompts are never used
  Leave it to each     the group has no say; each watch's own AI settings apply

Only "On" makes anything cascade, so it decides both:

  * whether the evaluator inherits the group's prompts (resolve_llm_field /
    get_effective_summary_prompt), and
  * whether the watch edit page shows the inherited value as a
    "From group '<name>': <value>" placeholder.

So every UI assertion here is paired: group On → "From group ..." visible, group Off or
undecided → not a trace of it. On a watch the same field is a plain on/off checkbox (#4204).
"""

import html
import json

from flask import url_for

from changedetectionio.tests.util import live_server_setup, delete_all_watches


# The exact rendered string under test, from templates/edit/include_llm_intent.html:
#   {% set intent_placeholder = _("From group '%(name)s': %(value)s", ...) %}
def _from_group_text(name, value):
    return f"From group '{name}': {value}"


def _page_text(res):
    """Response body with HTML entities resolved, so we can match the placeholder as written."""
    return html.unescape(res.data.decode('utf-8', errors='replace'))


def _input_tags(body, name):
    """Every whole <input ...> tag carrying name="<name>", in document order."""
    tags = []
    pos = body.find(f'name="{name}"')
    while pos != -1:
        start = body.rfind('<input', 0, pos)
        end = body.find('>', pos)
        tags.append(body[start:end + 1])
        pos = body.find(f'name="{name}"', end)
    return tags


def _input_tag(body, name):
    """Return the first <input ...> tag carrying name="<name>", or '' if there isn't one."""
    tags = _input_tags(body, name)
    return tags[0] if tags else ''


def _checkbox_is_checked(body, name):
    """True when that checkbox renders as checked (attribute order is not guaranteed)."""
    tag = _input_tag(body, name)
    assert tag, f'no <input name="{name}"> in the page'
    return 'checked' in tag


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _configure_llm(datastore):
    """Enable a fake LLM so the AI section is visible in the edit form."""
    app = datastore.data['settings']['application']
    if 'llm' not in app:
        app['llm'] = {}
    app['llm'].update({'model': 'gpt-4o-mini', 'api_key': 'sk-test'})


def _create_watch(client, test_url, api_token):
    res = client.post(
        '/api/v1/watch',
        data=json.dumps({'url': test_url}),
        headers={'content-type': 'application/json', 'x-api-key': api_token},
        follow_redirects=True,
    )
    assert res.status_code == 201
    return res.json['uuid']


def _api_token(client):
    return client.application.config.get('DATASTORE').data['settings']['application'].get('api_access_token')


# ---------------------------------------------------------------------------
# Tag setup
# ---------------------------------------------------------------------------

def _add_tag_with_llm(datastore, title, llm_intent='', llm_change_summary='', ai=True):
    """Create a tag with LLM fields set directly in the datastore.

    `ai` is the group's single AI control (llm_backend_profile): True = On, False = Off,
    None = leave it to each watch. Defaults to True because most cases here are about what
    a group set to "On" hands down.
    """
    tag_uuid = datastore.add_tag(title)
    tag = datastore.data['settings']['application']['tags'][tag_uuid]
    if llm_intent:
        tag['llm_intent'] = llm_intent
    if llm_change_summary:
        tag['llm_change_summary'] = llm_change_summary
    tag['llm_backend_profile'] = ai
    return tag_uuid


def _link_watch_to_tag(datastore, watch_uuid, tag_uuid):
    """Append a tag UUID to a watch's tags list."""
    watch = datastore.data['watching'][watch_uuid]
    tags = list(watch.get('tags') or [])
    if tag_uuid not in tags:
        tags.append(tag_uuid)
    watch['tags'] = tags


# ---------------------------------------------------------------------------
# The group's one AI control — ternary on a group, checkbox on a watch
# ---------------------------------------------------------------------------

def test_group_edit_page_has_the_ternary_ai_control(
        client, live_server, measure_memory_usage, datastore_path):
    """
    The group edit page must offer all three states — without them there is no way to turn
    group-wide AI settings on, or to switch AI off for a whole group (#4204).
    """
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)

    tag_uuid = ds.add_tag('Ternary Group')

    res = client.get(url_for('tags.form_tag_edit', uuid=tag_uuid))
    assert res.status_code == 200
    body = res.data.decode('utf-8', errors='replace')
    text = _page_text(res)

    assert 'name="llm_backend_profile"' in body, \
        "group edit page is missing the 'AI for watches in this group' control"
    for value in ('true', 'false', 'none'):
        assert f'name="llm_backend_profile" value="{value}"' in body, \
            f"group AI control is missing its '{value}' option"
    assert 'AI for watches in this group' in text
    assert 'Leave it to each watch' in text
    # New groups start undecided, so they never touch their watches
    assert 'id="llm_backend_profile_none" checked' in body, \
        "a new group must default to 'Leave it to each watch'"

    delete_all_watches(client)


def test_watch_edit_page_has_a_plain_ai_checkbox(
        client, live_server, measure_memory_usage, datastore_path):
    """A watch gets a simple on/off, not the group's three-way choice."""
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    api_token = _api_token(client)
    watch_uuid = _create_watch(client, url_for('test_endpoint', _external=True), api_token)

    res = client.get(url_for('ui.ui_edit.edit_page', uuid=watch_uuid))
    assert res.status_code == 200
    body = res.data.decode('utf-8', errors='replace')

    assert 'name="llm_intent"' in body  # AI section is rendered...
    assert 'type="checkbox"' in _input_tag(body, 'llm_backend_profile')
    assert 'Leave it to each watch' not in _page_text(res), \
        "the group's three-way AI choice must not appear on a watch"

    delete_all_watches(client)


def test_group_edit_page_never_shows_the_from_group_placeholder(
        client, live_server, measure_memory_usage, datastore_path):
    """
    "From group ..." describes something inherited by a watch; the group edit page is
    where the value is authored, so it must show group-flavoured copy instead.
    """
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)

    tag_uuid = _add_tag_with_llm(ds, 'Authoring Group', llm_intent='Group intent value')

    res = client.get(url_for('tags.form_tag_edit', uuid=tag_uuid))
    assert res.status_code == 200
    text = _page_text(res)

    assert 'From group' not in text
    # Group copy, not the per-watch copy (both live in the same shared include)
    assert 'Set a change intent for all watches in this tag/group' in text
    assert 'Describe what you care about' not in text

    delete_all_watches(client)


def test_group_edit_form_saves_and_reloads_each_ai_state(
        client, live_server, measure_memory_usage, datastore_path):
    """All three states round-trip through the real form, and the prompt is kept regardless."""
    res = client.post(url_for('tags.form_tag_add'), data={'name': 'Saved Group'}, follow_redirects=True)
    assert b'Tag added' in res.data

    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    tag_uuid = list(ds.data['settings']['application']['tags'].keys())[0]

    for posted, expected in (('true', True), ('false', False), ('none', None)):
        res = client.post(
            url_for('tags.form_tag_edit_submit', uuid=tag_uuid),
            data={'title': 'Saved Group',
                  'llm_intent': 'Only notify me about price drops',
                  'llm_backend_profile': posted},
            follow_redirects=True,
        )
        assert b'Updated' in res.data
        tag = ds.data['settings']['application']['tags'][tag_uuid]
        assert tag.get('llm_backend_profile') is expected, f"posting {posted!r} should store {expected!r}"
        # The prompt is always kept — the AI state only decides whether it is used
        assert tag.get('llm_intent') == 'Only notify me about price drops'

        # ..and the reloaded page comes back on the same option
        body = client.get(url_for('tags.form_tag_edit', uuid=tag_uuid)).data.decode('utf-8', errors='replace')
        assert f'id="llm_backend_profile_{posted}" checked' in body, \
            f"saved state {posted!r} must render as the selected option"

    delete_all_watches(client)


# ---------------------------------------------------------------------------
# Watch edit page — llm_intent group override, gated on the checkbox
# ---------------------------------------------------------------------------

def test_watch_edit_shows_llm_intent_placeholder_when_group_overrides_enabled(
        client, live_server, measure_memory_usage, datastore_path):
    """
    Group override ON + watch has no own llm_intent → the edit page shows
    "From group '<name>': <value>" as the placeholder, and the field stays editable.
    """
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    api_token = _api_token(client)
    test_url = url_for('test_endpoint', _external=True)

    watch_uuid = _create_watch(client, test_url, api_token)
    tag_uuid = _add_tag_with_llm(ds, 'Price Watchers',
                                 llm_intent='Notify only when price drops',
                                 ai=True)
    _link_watch_to_tag(ds, watch_uuid, tag_uuid)

    res = client.get(url_for('ui.ui_edit.edit_page', uuid=watch_uuid))
    assert res.status_code == 200
    text = _page_text(res)

    assert 'name="llm_intent"' in text
    assert _from_group_text('Price Watchers', 'Notify only when price drops') in text, \
        "watch edit must show the inherited group intent as a 'From group ...' placeholder"

    # Field must be editable — no readonly attribute
    intent_pos = text.find('name="llm_intent"')
    snippet = text[max(0, intent_pos - 50): intent_pos + 300]
    assert 'readonly' not in snippet, \
        f"llm_intent must be editable when group sets it; snippet: {snippet!r}"

    delete_all_watches(client)


def test_watch_edit_hides_llm_intent_placeholder_when_group_overrides_disabled(
        client, live_server, measure_memory_usage, datastore_path):
    """
    Same group, same intent, checkbox OFF → no "From group ..." anywhere, and the
    generic example placeholder is used instead. This is the pairing that makes the
    checkbox meaningful.
    """
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    api_token = _api_token(client)
    test_url = url_for('test_endpoint', _external=True)

    watch_uuid = _create_watch(client, test_url, api_token)
    tag_uuid = _add_tag_with_llm(ds, 'Price Watchers',
                                 llm_intent='Notify only when price drops',
                                 ai=False)
    _link_watch_to_tag(ds, watch_uuid, tag_uuid)

    res = client.get(url_for('ui.ui_edit.edit_page', uuid=watch_uuid))
    assert res.status_code == 200
    text = _page_text(res)

    assert 'From group' not in text, \
        "group AI settings must not leak into the watch unless the group is set to On"
    assert 'Notify only when price drops' not in text
    # Falls back to the normal per-watch example placeholder
    assert 'e.g. Alert me when the price drops below $300' in text

    delete_all_watches(client)


def test_watch_edit_llm_intent_shows_own_value_not_group_placeholder(
        client, live_server, measure_memory_usage, datastore_path):
    """
    When the watch has its own llm_intent, the textarea body shows the watch's value
    and the placeholder does NOT say "From group" — even with the group opted in.
    """
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    api_token = _api_token(client)
    test_url = url_for('test_endpoint', _external=True)

    watch_uuid = _create_watch(client, test_url, api_token)
    tag_uuid = _add_tag_with_llm(ds, 'Deals Group',
                                 llm_intent='Tag intent: notify on any deal',
                                 ai=True)
    _link_watch_to_tag(ds, watch_uuid, tag_uuid)

    ds.data['watching'][watch_uuid]['llm_intent'] = 'My own watch intent'

    res = client.get(url_for('ui.ui_edit.edit_page', uuid=watch_uuid))
    assert res.status_code == 200
    text = _page_text(res)

    # Watch's own value in the textarea body
    assert 'My own watch intent' in text
    # No group placeholder — the watch has its own value
    assert 'From group' not in text

    delete_all_watches(client)


# ---------------------------------------------------------------------------
# Watch edit page — llm_change_summary group override, gated on the checkbox
# ---------------------------------------------------------------------------

def test_watch_edit_shows_llm_change_summary_placeholder_when_group_overrides_enabled(
        client, live_server, measure_memory_usage, datastore_path):
    """Group override ON → the group summary prompt shows as placeholder (editable)."""
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    api_token = _api_token(client)
    test_url = url_for('test_endpoint', _external=True)

    watch_uuid = _create_watch(client, test_url, api_token)
    tag_uuid = _add_tag_with_llm(
        ds, 'Summary Group',
        llm_change_summary='List new items as bullet points. Translate to English.',
        ai=True,
    )
    _link_watch_to_tag(ds, watch_uuid, tag_uuid)

    res = client.get(url_for('ui.ui_edit.edit_page', uuid=watch_uuid))
    assert res.status_code == 200
    text = _page_text(res)

    assert _from_group_text('Summary Group',
                            'List new items as bullet points. Translate to English.') in text

    # Field must be editable
    summary_pos = text.find('name="llm_change_summary"')
    assert summary_pos != -1
    snippet = text[max(0, summary_pos - 50): summary_pos + 300]
    assert 'readonly' not in snippet, \
        f"llm_change_summary must be editable; snippet: {snippet!r}"

    delete_all_watches(client)


def test_watch_edit_hides_llm_change_summary_placeholder_when_group_overrides_disabled(
        client, live_server, measure_memory_usage, datastore_path):
    """Group override OFF → no "From group ..." for the summary prompt either."""
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    api_token = _api_token(client)
    test_url = url_for('test_endpoint', _external=True)

    watch_uuid = _create_watch(client, test_url, api_token)
    tag_uuid = _add_tag_with_llm(
        ds, 'Summary Group',
        llm_change_summary='List new items as bullet points. Translate to English.',
        ai=False,
    )
    _link_watch_to_tag(ds, watch_uuid, tag_uuid)

    res = client.get(url_for('ui.ui_edit.edit_page', uuid=watch_uuid))
    assert res.status_code == 200
    text = _page_text(res)

    assert 'From group' not in text
    assert 'List new items as bullet points' not in text

    delete_all_watches(client)


def test_watch_edit_llm_change_summary_shows_own_value_not_group_placeholder(
        client, live_server, measure_memory_usage, datastore_path):
    """
    When the watch has its own llm_change_summary, the textarea body shows the watch's
    value and no group placeholder appears.
    """
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    api_token = _api_token(client)
    test_url = url_for('test_endpoint', _external=True)

    watch_uuid = _create_watch(client, test_url, api_token)
    tag_uuid = _add_tag_with_llm(ds, 'Summary Group', llm_change_summary='Tag summary prompt',
                                 ai=True)
    _link_watch_to_tag(ds, watch_uuid, tag_uuid)

    ds.data['watching'][watch_uuid]['llm_change_summary'] = 'My own summary prompt'

    res = client.get(url_for('ui.ui_edit.edit_page', uuid=watch_uuid))
    assert res.status_code == 200
    text = _page_text(res)

    assert 'My own summary prompt' in text
    assert 'From group' not in text

    delete_all_watches(client)


# ---------------------------------------------------------------------------
# No tag linked — fields are editable
# ---------------------------------------------------------------------------

def test_watch_edit_no_tag_fields_are_editable(
        client, live_server, measure_memory_usage, datastore_path):
    """
    A watch with no tags: both LLM textareas are editable (no readonly, no From group).
    """
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    api_token = _api_token(client)
    test_url = url_for('test_endpoint', _external=True)

    watch_uuid = _create_watch(client, test_url, api_token)

    res = client.get(url_for('ui.ui_edit.edit_page', uuid=watch_uuid))
    assert res.status_code == 200
    body = res.data.decode('utf-8', errors='replace')

    # Neither textarea should be readonly
    for field in ('llm_intent', 'llm_change_summary'):
        pos = body.find(f'name="{field}"')
        assert pos != -1, f"{field} textarea missing from watch edit page"
        snippet = body[max(0, pos - 50): pos + 300]
        assert 'readonly' not in snippet, \
            f"{field} textarea must not be readonly with no tags; snippet: {snippet!r}"

    assert 'From group' not in body

    delete_all_watches(client)


# ---------------------------------------------------------------------------
# Evaluator cascade — gated on the same checkbox as the UI
# ---------------------------------------------------------------------------

def test_resolve_llm_field_uses_tag_value_when_group_overrides_enabled(
        client, live_server, measure_memory_usage, datastore_path):
    """
    resolve_llm_field returns the tag's value (and tag name as source) when the watch
    has no own value and the group is opted in.
    """
    from changedetectionio.llm.evaluator import resolve_llm_field

    ds = client.application.config.get('DATASTORE')
    api_token = _api_token(client)
    test_url = url_for('test_endpoint', _external=True)

    watch_uuid = _create_watch(client, test_url, api_token)
    tag_uuid = _add_tag_with_llm(ds, 'Cascade Group', llm_intent='Group-level intent',
                                 ai=True)
    _link_watch_to_tag(ds, watch_uuid, tag_uuid)

    watch = ds.data['watching'][watch_uuid]
    value, source = resolve_llm_field(watch, ds, 'llm_intent')

    assert value == 'Group-level intent'
    assert source == 'Cascade Group'

    delete_all_watches(client)


def test_resolve_llm_field_ignores_tag_value_when_group_overrides_disabled(
        client, live_server, measure_memory_usage, datastore_path):
    """The UI hint and the evaluator agree: no opt-in, no inheritance."""
    from changedetectionio.llm.evaluator import resolve_llm_field

    ds = client.application.config.get('DATASTORE')
    api_token = _api_token(client)
    test_url = url_for('test_endpoint', _external=True)

    watch_uuid = _create_watch(client, test_url, api_token)
    tag_uuid = _add_tag_with_llm(ds, 'Cascade Group', llm_intent='Group-level intent',
                                 ai=False)
    _link_watch_to_tag(ds, watch_uuid, tag_uuid)

    watch = ds.data['watching'][watch_uuid]
    value, source = resolve_llm_field(watch, ds, 'llm_intent')

    assert value == ''
    assert source == ''

    delete_all_watches(client)


def test_resolve_llm_field_uses_watch_value_over_tag(
        client, live_server, measure_memory_usage, datastore_path):
    """
    resolve_llm_field prefers the watch's own value over the tag's, opted in or not.
    """
    from changedetectionio.llm.evaluator import resolve_llm_field

    ds = client.application.config.get('DATASTORE')
    api_token = _api_token(client)
    test_url = url_for('test_endpoint', _external=True)

    watch_uuid = _create_watch(client, test_url, api_token)
    tag_uuid = _add_tag_with_llm(ds, 'Override Group', llm_intent='Tag intent',
                                 ai=True)
    _link_watch_to_tag(ds, watch_uuid, tag_uuid)

    ds.data['watching'][watch_uuid]['llm_intent'] = 'Watch-level intent'
    watch = ds.data['watching'][watch_uuid]

    value, source = resolve_llm_field(watch, ds, 'llm_intent')

    assert value == 'Watch-level intent'
    assert source == 'watch'

    delete_all_watches(client)


# ---------------------------------------------------------------------------
# Both fields overridden independently
# ---------------------------------------------------------------------------

def test_watch_edit_independent_field_overrides(
        client, live_server, measure_memory_usage, datastore_path):
    """
    llm_intent can be inherited from an opted-in group while llm_change_summary
    is the watch's own value.
    """
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    api_token = _api_token(client)
    test_url = url_for('test_endpoint', _external=True)

    watch_uuid = _create_watch(client, test_url, api_token)
    tag_uuid = _add_tag_with_llm(
        ds, 'Mixed Group',
        llm_intent='Group intent here',
        llm_change_summary='Group summary here',
        ai=True,
    )
    _link_watch_to_tag(ds, watch_uuid, tag_uuid)

    # Watch overrides only llm_change_summary
    ds.data['watching'][watch_uuid]['llm_change_summary'] = 'My own summary'

    res = client.get(url_for('ui.ui_edit.edit_page', uuid=watch_uuid))
    assert res.status_code == 200
    text = _page_text(res)

    # llm_intent: group placeholder visible (watch has no own value)
    assert _from_group_text('Mixed Group', 'Group intent here') in text
    intent_pos = text.find('name="llm_intent"')
    assert intent_pos != -1
    intent_snippet = text[max(0, intent_pos - 50): intent_pos + 300]
    assert 'readonly' not in intent_snippet, \
        f"llm_intent must be editable even when group sets it; snippet: {intent_snippet!r}"

    # llm_change_summary: watch own value shown in body, no group placeholder for it
    assert 'My own summary' in text
    assert _from_group_text('Mixed Group', 'Group summary here') not in text
    summary_pos = text.find('name="llm_change_summary"')
    assert summary_pos != -1
    summary_snippet = text[max(0, summary_pos - 50): summary_pos + 300]
    assert 'readonly' not in summary_snippet, \
        f"llm_change_summary should be editable; snippet: {summary_snippet!r}"

    delete_all_watches(client)


# ---------------------------------------------------------------------------
# Tag edit page — AI section is always visible regardless of processor
# ---------------------------------------------------------------------------

def test_tag_edit_page_shows_ai_section(
        client, live_server, measure_memory_usage, datastore_path):
    """
    The tag/group edit page must always show the AI Intent and AI Change Summary
    textareas when LLM is configured, regardless of whether the tag has a
    'processor' key set (e.g. restock_diff tags must still show AI fields).
    """
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)

    tag_uuid = ds.add_tag('Test AI Group')

    # Simulate a tag that has processor set (e.g. saved via restock form)
    ds.data['settings']['application']['tags'][tag_uuid]['processor'] = 'restock_diff'

    res = client.get(url_for('tags.form_tag_edit', uuid=tag_uuid))
    assert res.status_code == 200
    body = res.data.decode('utf-8', errors='replace')

    # Both AI textareas must appear
    assert 'name="llm_intent"' in body, \
        "llm_intent textarea missing from tag edit page — processor check incorrectly blocks it"
    assert 'name="llm_change_summary"' in body, \
        "llm_change_summary textarea missing from tag edit page"

    # Neither should be readonly in tag context
    for field in ('llm_intent', 'llm_change_summary'):
        pos = body.find(f'name="{field}"')
        snippet = body[max(0, pos - 50): pos + 300]
        assert 'readonly' not in snippet, \
            f"{field} must not be readonly in tag edit context; snippet: {snippet!r}"

    delete_all_watches(client)


def test_tag_edit_page_shows_prompt_mode_radio(
        client, live_server, measure_memory_usage, datastore_path):
    """
    A group must also be able to append to the global prompt rather than replace it,
    so the mode radio has to render on the tag edit page too. Re #4251.
    """
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)

    tag_uuid = ds.add_tag('Append Group')

    res = client.get(url_for('tags.form_tag_edit', uuid=tag_uuid))
    assert res.status_code == 200
    body = res.data.decode('utf-8', errors='replace')

    assert 'name="llm_change_summary_mode"' in body, \
        "prompt mode radio missing from tag edit page"
    assert 'value="replace"' in body
    assert 'value="append"' in body

    delete_all_watches(client)


def test_tag_append_mode_persists_and_applies(
        client, live_server, measure_memory_usage, datastore_path):
    """An opted-in group set to append adds its text to the global prompt for its watches."""
    from changedetectionio.llm.evaluator import get_effective_summary_prompt

    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    ds.data['settings']['application']['llm']['change_summary_default'] = 'GLOBAL RULES'

    api_token = _api_token(client)
    test_url = url_for('test_endpoint', _external=True)
    watch_uuid = _create_watch(client, test_url, api_token)

    tag_uuid = _add_tag_with_llm(ds, 'Append Group', llm_change_summary='Group extra line.',
                                 ai=True)
    ds.data['settings']['application']['tags'][tag_uuid]['llm_change_summary_mode'] = 'append'
    _link_watch_to_tag(ds, watch_uuid, tag_uuid)

    watch = ds.data['watching'][watch_uuid]
    assert get_effective_summary_prompt(watch, ds) == 'GLOBAL RULES\n\nGroup extra line.'

    delete_all_watches(client)


def test_tag_append_mode_ignored_when_group_overrides_disabled(
        client, live_server, measure_memory_usage, datastore_path):
    """Without the opt-in the group's appended text never reaches the effective prompt."""
    from changedetectionio.llm.evaluator import get_effective_summary_prompt

    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    ds.data['settings']['application']['llm']['change_summary_default'] = 'GLOBAL RULES'

    api_token = _api_token(client)
    test_url = url_for('test_endpoint', _external=True)
    watch_uuid = _create_watch(client, test_url, api_token)

    tag_uuid = _add_tag_with_llm(ds, 'Append Group', llm_change_summary='Group extra line.',
                                 ai=False)
    ds.data['settings']['application']['tags'][tag_uuid]['llm_change_summary_mode'] = 'append'
    _link_watch_to_tag(ds, watch_uuid, tag_uuid)

    watch = ds.data['watching'][watch_uuid]
    assert get_effective_summary_prompt(watch, ds) == 'GLOBAL RULES'

    delete_all_watches(client)


# ---------------------------------------------------------------------------
# AI on/off per watch, and per group when the group overrides — #4204
# ---------------------------------------------------------------------------

def test_watch_edit_has_ai_enabled_checkbox(
        client, live_server, measure_memory_usage, datastore_path):
    """Every watch gets its own AI on/off switch, on by default."""
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    api_token = _api_token(client)
    watch_uuid = _create_watch(client, url_for('test_endpoint', _external=True), api_token)

    res = client.get(url_for('ui.ui_edit.edit_page', uuid=watch_uuid))
    body = res.data.decode('utf-8', errors='replace')

    assert 'name="llm_backend_profile"' in body, \
        "watch edit page is missing the AI on/off checkbox (#4204)"
    assert _checkbox_is_checked(body, 'llm_backend_profile'), \
        "AI should default to on for a new watch"
    # No group involved, so no override note
    assert 'overrides this' not in _page_text(res)

    delete_all_watches(client)


def test_group_edit_can_switch_ai_off_for_the_whole_group(
        client, live_server, measure_memory_usage, datastore_path):
    """The group's control has an explicit "Off for every watch" state — the #4204 ask."""
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    tag_uuid = ds.add_tag('AI Toggle Group')

    res = client.get(url_for('tags.form_tag_edit', uuid=tag_uuid))
    assert 'Off for every watch' in _page_text(res), \
        "group edit page cannot switch AI off for all of its watches (#4204)"

    delete_all_watches(client)


def test_group_edit_greys_out_the_prompts_unless_ai_is_on(
        client, live_server, measure_memory_usage, datastore_path):
    """
    Same cue as the restock group override (#overrides_watch + toggleOpacity): the prompts
    only mean something in the "On" state, so they are greyed out otherwise. The state
    changes without a reload, so this pins the JS wiring rather than the opacity value.
    """
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    tag_uuid = ds.add_tag('Dimmed Group')

    res = client.get(url_for('tags.form_tag_edit', uuid=tag_uuid))
    body = res.data.decode('utf-8', errors='replace')

    assert "toggleOpacityByRadioValue('llm_backend_profile', 'true'" in body, \
        "group edit page lost the wiring that greys out the AI prompts"
    # ..and the elements it drives are all present
    for element_id in ('llm_backend_profile_true', 'change-intent-notify-me-when', 'change-summary'):
        assert f'id="{element_id}"' in body, f"#{element_id} missing — opacity toggle would be a no-op"

    delete_all_watches(client)


def test_watch_edit_shows_which_group_decided_the_ai_switch(
        client, live_server, measure_memory_usage, datastore_path):
    """
    A group that has taken the decision decides for its watches, so the watch edit page says
    which group is in charge and what it decided — and that explanation must stay readable
    (only the checkbox it describes is dimmed).
    """
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    api_token = _api_token(client)
    watch_uuid = _create_watch(client, url_for('test_endpoint', _external=True), api_token)

    tag_uuid = _add_tag_with_llm(ds, 'Tech news', ai=False)
    _link_watch_to_tag(ds, watch_uuid, tag_uuid)

    res = client.get(url_for('ui.ui_edit.edit_page', uuid=watch_uuid))
    text = _page_text(res)
    assert 'decides this: AI is OFF for every watch in that group.' in text

    # The group name links to that group's edit page, straight to its AI tab
    tag_edit_url = url_for('tags.form_tag_edit', uuid=tag_uuid)
    assert f'<a href="{tag_edit_url}#ai-llm">Tech news</a>' in text, \
        "the group name in the note must link to the group's edit page"

    # The note itself is not inside the dimmed wrapper
    note_pos = text.find('decides this: AI is OFF')
    dimmed_pos = text.find('style="opacity: 0.6;"', text.find('id="llm-ai-enabled-row"'))
    assert dimmed_pos != -1, "the overridden checkbox should be dimmed"
    assert text.find('</div>', dimmed_pos) < note_pos, \
        "the 'Group X decides this' note must not be greyed out with the checkbox"

    # Group switched to On → the note reflects that, still linked
    ds.data['settings']['application']['tags'][tag_uuid]['llm_backend_profile'] = True
    text = _page_text(client.get(url_for('ui.ui_edit.edit_page', uuid=watch_uuid)))
    assert 'decides this: AI is ON for every watch in that group.' in text
    assert f'<a href="{tag_edit_url}#ai-llm">Tech news</a>' in text

    # ..and the watch's own checkbox is disabled, showing what the group decided
    body = client.get(url_for('ui.ui_edit.edit_page', uuid=watch_uuid)).data.decode('utf-8', errors='replace')
    checkbox = _input_tags(body, 'llm_backend_profile')[0]
    assert 'disabled' in checkbox, "the group decides, so the watch's own checkbox must be disabled"
    assert 'checked' in checkbox, "disabled checkbox must show the state the group decided (ON)"

    ds.data['settings']['application']['tags'][tag_uuid]['llm_backend_profile'] = False
    body = client.get(url_for('ui.ui_edit.edit_page', uuid=watch_uuid)).data.decode('utf-8', errors='replace')
    checkbox = _input_tags(body, 'llm_backend_profile')[0]
    assert 'disabled' in checkbox and 'checked' not in checkbox, \
        "disabled checkbox must show the state the group decided (OFF)"

    # ..and with the group leaving it to each watch, the watch is on its own again
    ds.data['settings']['application']['tags'][tag_uuid]['llm_backend_profile'] = None
    res = client.get(url_for('ui.ui_edit.edit_page', uuid=watch_uuid))
    assert 'decides this' not in _page_text(res)

    delete_all_watches(client)


def test_watch_own_ai_switch_survives_being_overridden_by_a_group(
        client, live_server, measure_memory_usage, datastore_path):
    """
    While a group decides, the watch's checkbox is disabled — and a disabled checkbox is not
    POSTed, which for a checkbox reads as "off". Saving the watch must therefore NOT quietly
    rewrite its own preference: it has to come back unchanged once the group stops deciding.
    """
    from changedetectionio.llm.evaluator import llm_enabled_for_watch

    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    api_token = _api_token(client)
    test_url = url_for('test_endpoint', _external=True)
    watch_uuid = _create_watch(client, test_url, api_token)

    # Watch says AI on (the default); the group overrules it with "off"
    tag_uuid = _add_tag_with_llm(ds, 'Deciding Group', ai=False)
    _link_watch_to_tag(ds, watch_uuid, tag_uuid)
    assert ds.data['watching'][watch_uuid].get('llm_backend_profile') is True
    assert llm_enabled_for_watch(ds.data['watching'][watch_uuid], ds) == (False, 'Deciding Group')

    # Save the page exactly as the browser would: the disabled checkbox sends nothing at all
    res = client.post(
        url_for('ui.ui_edit.edit_page', uuid=watch_uuid),
        data={'url': test_url, 'fetch_backend': 'html_requests',
              'time_between_check_use_default': 'y'},
        follow_redirects=True,
    )
    assert b'Updated watch' in res.data

    watch = ds.data['watching'][watch_uuid]
    assert watch.get('llm_backend_profile') is True, \
        "saving while a group decides must not overwrite the watch's own AI preference"
    # Not even a hand-crafted POST can write it while it isn't user-editable
    res = client.post(
        url_for('ui.ui_edit.edit_page', uuid=watch_uuid),
        data={'url': test_url, 'fetch_backend': 'html_requests',
              'time_between_check_use_default': 'y', 'llm_backend_profile': ''},
        follow_redirects=True,
    )
    assert b'Updated watch' in res.data
    watch = ds.data['watching'][watch_uuid]
    assert watch.get('llm_backend_profile') is True
    # The group still wins for now...
    assert llm_enabled_for_watch(watch, ds) == (False, 'Deciding Group')
    # ..and when the group stops deciding, the watch's untouched preference applies again
    ds.data['settings']['application']['tags'][tag_uuid]['llm_backend_profile'] = None
    assert llm_enabled_for_watch(watch, ds) == (True, 'watch')

    delete_all_watches(client)


def test_watch_ai_switch_saves_via_edit_form(
        client, live_server, measure_memory_usage, datastore_path):
    """Turning AI off on a watch persists, and turning it back on works."""
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    api_token = _api_token(client)
    test_url = url_for('test_endpoint', _external=True)
    watch_uuid = _create_watch(client, test_url, api_token)

    from changedetectionio.llm.evaluator import llm_enabled_for_watch

    # Unchecked checkbox is simply absent from the POST
    res = client.post(
        url_for('ui.ui_edit.edit_page', uuid=watch_uuid),
        data={'url': test_url, 'fetch_backend': 'html_requests',
              'time_between_check_use_default': 'y'},
        follow_redirects=True,
    )
    assert b'Updated watch' in res.data
    watch = ds.data['watching'][watch_uuid]
    assert watch.get('llm_backend_profile') is False
    assert llm_enabled_for_watch(watch, ds) == (False, 'watch')

    res = client.post(
        url_for('ui.ui_edit.edit_page', uuid=watch_uuid),
        data={'url': test_url, 'fetch_backend': 'html_requests',
              'time_between_check_use_default': 'y', 'llm_backend_profile': 'y'},
        follow_redirects=True,
    )
    assert b'Updated watch' in res.data
    watch = ds.data['watching'][watch_uuid]
    assert watch.get('llm_backend_profile') is True
    assert llm_enabled_for_watch(watch, ds) == (True, 'watch')

    delete_all_watches(client)


def test_group_ai_switch_saves_and_decides_for_its_watches(
        client, live_server, measure_memory_usage, datastore_path):
    """
    Group form set to "Off for every watch" → every watch in the group is off, whatever the
    watch itself says. This is the #4204 "turn AI off for a whole group" flow.
    """
    from changedetectionio.llm.evaluator import llm_enabled_for_watch

    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    api_token = _api_token(client)
    watch_uuid = _create_watch(client, url_for('test_endpoint', _external=True), api_token)

    res = client.post(url_for('tags.form_tag_add'), data={'name': 'Budget Group'}, follow_redirects=True)
    assert b'Tag added' in res.data
    tag_uuid = [u for u, t in ds.data['settings']['application']['tags'].items()
                if t.get('title') == 'Budget Group'][0]

    res = client.post(
        url_for('tags.form_tag_edit_submit', uuid=tag_uuid),
        data={'title': 'Budget Group', 'llm_backend_profile': 'false'},
        follow_redirects=True,
    )
    assert b'Updated' in res.data
    tag = ds.data['settings']['application']['tags'][tag_uuid]
    assert tag.get('llm_backend_profile') is False

    _link_watch_to_tag(ds, watch_uuid, tag_uuid)
    watch = ds.data['watching'][watch_uuid]
    assert watch.get('llm_backend_profile') is True  # the watch itself still says "on"
    assert llm_enabled_for_watch(watch, ds) == (False, 'Budget Group'), \
        "a group set to Off must win over the watch's own AI switch"

    delete_all_watches(client)


def test_group_ai_state_survives_a_save_with_no_llm_configured(
        client, live_server, measure_memory_usage, datastore_path):
    """
    With no provider configured the AI control isn't rendered, and an unrendered control is
    indistinguishable from "off" in a POST — so the page must carry the saved state in a
    hidden input, otherwise merely saving the group would switch AI off.
    """
    ds = client.application.config.get('DATASTORE')
    # deliberately NOT calling _configure_llm

    res = client.post(url_for('tags.form_tag_add'), data={'name': 'Unconfigured Group'}, follow_redirects=True)
    assert b'Tag added' in res.data
    tag_uuid = [u for u, t in ds.data['settings']['application']['tags'].items()
                if t.get('title') == 'Unconfigured Group'][0]
    ds.data['settings']['application']['tags'][tag_uuid]['llm_backend_profile'] = True

    res = client.get(url_for('tags.form_tag_edit', uuid=tag_uuid))
    body = res.data.decode('utf-8', errors='replace')
    assert 'name="llm_intent"' not in body, "AI fields should not render without a provider"
    hidden = _input_tag(body, 'llm_backend_profile')
    assert 'type="hidden"' in hidden and 'value="true"' in hidden, \
        "the group AI state must be preserved in a hidden input when the AI section is not rendered"

    # Submit exactly what that page would send
    res = client.post(
        url_for('tags.form_tag_edit_submit', uuid=tag_uuid),
        data={'title': 'Unconfigured Group', 'llm_backend_profile': 'true'},
        follow_redirects=True,
    )
    assert b'Updated' in res.data

    tag = ds.data['settings']['application']['tags'][tag_uuid]
    assert tag.get('llm_backend_profile') is True, \
        "saving with the AI section hidden must not switch AI off"

    delete_all_watches(client)


# ---------------------------------------------------------------------------
# End-to-end through the real forms — the path the user actually clicks
# ---------------------------------------------------------------------------

def test_group_override_round_trip_through_both_forms(
        client, live_server, measure_memory_usage, datastore_path):
    """
    Set the group to On with an intent via the group form, tag a watch with it, and the watch
    edit page shows the inherited value as its placeholder. This is the flow that was broken:
    the group had no way to switch group-wide AI settings on at all.
    """
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    api_token = _api_token(client)
    test_url = url_for('test_endpoint', _external=True)
    watch_uuid = _create_watch(client, test_url, api_token)

    res = client.post(url_for('tags.form_tag_add'), data={'name': 'E2E Group'}, follow_redirects=True)
    assert b'Tag added' in res.data
    tag_uuid = [u for u, t in ds.data['settings']['application']['tags'].items()
                if t.get('title') == 'E2E Group'][0]

    res = client.post(
        url_for('tags.form_tag_edit_submit', uuid=tag_uuid),
        data={'title': 'E2E Group',
              'llm_intent': 'Only tell me about stock changes',
              'llm_backend_profile': 'true'},
        follow_redirects=True,
    )
    assert b'Updated' in res.data

    _link_watch_to_tag(ds, watch_uuid, tag_uuid)

    res = client.get(url_for('ui.ui_edit.edit_page', uuid=watch_uuid))
    assert _from_group_text('E2E Group', 'Only tell me about stock changes') in _page_text(res)

    delete_all_watches(client)
