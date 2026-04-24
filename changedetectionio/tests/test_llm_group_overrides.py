#!/usr/bin/env python3
"""
Tests for group/tag LLM field overrides on the watch edit page.

When a watch's first linked tag has llm_intent or llm_change_summary set
and the watch itself has no own value, the watch edit form should render
the relevant textarea as readonly with a "From group '<name>': <value>"
placeholder.

When the watch has its own value, the textarea is editable as normal.

The evaluator cascade (resolve_llm_field) is already tested in the
evaluator unit tests; these tests focus on the UI and form behaviour.
"""

import json

from flask import url_for

from changedetectionio.tests.util import live_server_setup, delete_all_watches


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

def _add_tag_with_llm(datastore, title, llm_intent='', llm_change_summary=''):
    """Create a tag with LLM fields set directly in the datastore."""
    tag_uuid = datastore.add_tag(title)
    tag = datastore.data['settings']['application']['tags'][tag_uuid]
    if llm_intent:
        tag['llm_intent'] = llm_intent
    if llm_change_summary:
        tag['llm_change_summary'] = llm_change_summary
    return tag_uuid


def _link_watch_to_tag(datastore, watch_uuid, tag_uuid):
    """Append a tag UUID to a watch's tags list."""
    watch = datastore.data['watching'][watch_uuid]
    tags = list(watch.get('tags') or [])
    if tag_uuid not in tags:
        tags.append(tag_uuid)
    watch['tags'] = tags


# ---------------------------------------------------------------------------
# Watch edit page — llm_intent group override
# ---------------------------------------------------------------------------

def test_watch_edit_shows_llm_intent_placeholder_from_group(
        client, live_server, measure_memory_usage, datastore_path):
    """
    When a watch has no own llm_intent but its first tag does,
    the edit page must show "From group" + group name + group value in the
    placeholder so the user sees the inherited value but can still type to override.
    The field must NOT be readonly.
    """
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    api_token = _api_token(client)
    test_url = url_for('test_endpoint', _external=True)

    watch_uuid = _create_watch(client, test_url, api_token)
    tag_uuid = _add_tag_with_llm(ds, 'Price Watchers', llm_intent='Notify only when price drops')
    _link_watch_to_tag(ds, watch_uuid, tag_uuid)

    res = client.get(url_for('ui.ui_edit.edit_page', uuid=watch_uuid))
    assert res.status_code == 200
    body = res.data.decode('utf-8', errors='replace')

    assert 'name="llm_intent"' in body

    # Placeholder must contain "From group", the tag name, and the value
    assert 'From group' in body
    assert 'Price Watchers' in body
    assert 'Notify only when price drops' in body

    # Field must be editable — no readonly attribute
    intent_pos = body.find('name="llm_intent"')
    snippet = body[max(0, intent_pos - 50): intent_pos + 300]
    assert 'readonly' not in snippet, \
        f"llm_intent must be editable when group sets it; snippet: {snippet!r}"

    delete_all_watches(client)


def test_watch_edit_llm_intent_shows_own_value_not_group_placeholder(
        client, live_server, measure_memory_usage, datastore_path):
    """
    When a watch has its own llm_intent, the textarea body shows the watch's value
    and the placeholder does NOT say "From group" (the group value is irrelevant).
    """
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    api_token = _api_token(client)
    test_url = url_for('test_endpoint', _external=True)

    watch_uuid = _create_watch(client, test_url, api_token)
    tag_uuid = _add_tag_with_llm(ds, 'Deals Group', llm_intent='Tag intent: notify on any deal')
    _link_watch_to_tag(ds, watch_uuid, tag_uuid)

    ds.data['watching'][watch_uuid]['llm_intent'] = 'My own watch intent'

    res = client.get(url_for('ui.ui_edit.edit_page', uuid=watch_uuid))
    assert res.status_code == 200
    body = res.data.decode('utf-8', errors='replace')

    # Watch's own value in the textarea body
    assert 'My own watch intent' in body
    # No group placeholder — the watch has its own value
    assert 'From group' not in body

    delete_all_watches(client)


# ---------------------------------------------------------------------------
# Watch edit page — llm_change_summary group override
# ---------------------------------------------------------------------------

def test_watch_edit_shows_llm_change_summary_placeholder_from_group(
        client, live_server, measure_memory_usage, datastore_path):
    """
    When a watch has no own llm_change_summary but its first tag does,
    the edit page shows the group value as placeholder (editable, not readonly).
    """
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    api_token = _api_token(client)
    test_url = url_for('test_endpoint', _external=True)

    watch_uuid = _create_watch(client, test_url, api_token)
    tag_uuid = _add_tag_with_llm(
        ds, 'Summary Group',
        llm_change_summary='List new items as bullet points. Translate to English.'
    )
    _link_watch_to_tag(ds, watch_uuid, tag_uuid)

    res = client.get(url_for('ui.ui_edit.edit_page', uuid=watch_uuid))
    assert res.status_code == 200
    body = res.data.decode('utf-8', errors='replace')

    assert 'Summary Group' in body
    assert 'List new items as bullet points' in body

    # Field must be editable
    summary_pos = body.find('name="llm_change_summary"')
    assert summary_pos != -1
    snippet = body[max(0, summary_pos - 50): summary_pos + 300]
    assert 'readonly' not in snippet, \
        f"llm_change_summary must be editable; snippet: {snippet!r}"

    delete_all_watches(client)


def test_watch_edit_llm_change_summary_shows_own_value_not_group_placeholder(
        client, live_server, measure_memory_usage, datastore_path):
    """
    When a watch has its own llm_change_summary, the textarea body shows the watch's
    value and no group placeholder appears.
    """
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    api_token = _api_token(client)
    test_url = url_for('test_endpoint', _external=True)

    watch_uuid = _create_watch(client, test_url, api_token)
    tag_uuid = _add_tag_with_llm(ds, 'Summary Group', llm_change_summary='Tag summary prompt')
    _link_watch_to_tag(ds, watch_uuid, tag_uuid)

    ds.data['watching'][watch_uuid]['llm_change_summary'] = 'My own summary prompt'

    res = client.get(url_for('ui.ui_edit.edit_page', uuid=watch_uuid))
    assert res.status_code == 200
    body = res.data.decode('utf-8', errors='replace')

    assert 'My own summary prompt' in body
    assert 'From group' not in body

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
        if pos == -1:
            continue  # field might not render if LLM section hidden for some reason
        snippet = body[max(0, pos - 50): pos + 300]
        assert 'readonly' not in snippet, \
            f"{field} textarea must not be readonly with no tags; snippet: {snippet!r}"

    assert 'From group' not in body

    delete_all_watches(client)


# ---------------------------------------------------------------------------
# Evaluator cascade — group value used when watch has none
# ---------------------------------------------------------------------------

def test_resolve_llm_field_uses_tag_value_when_watch_has_none(
        client, live_server, measure_memory_usage, datastore_path):
    """
    resolve_llm_field returns the tag's value (and tag name as source) when
    the watch has no own value.
    """
    from changedetectionio.llm.evaluator import resolve_llm_field

    ds = client.application.config.get('DATASTORE')
    api_token = _api_token(client)
    test_url = url_for('test_endpoint', _external=True)

    watch_uuid = _create_watch(client, test_url, api_token)
    tag_uuid = _add_tag_with_llm(ds, 'Cascade Group', llm_intent='Group-level intent')
    _link_watch_to_tag(ds, watch_uuid, tag_uuid)

    watch = ds.data['watching'][watch_uuid]
    value, source = resolve_llm_field(watch, ds, 'llm_intent')

    assert value == 'Group-level intent'
    assert source == 'Cascade Group'

    delete_all_watches(client)


def test_resolve_llm_field_uses_watch_value_over_tag(
        client, live_server, measure_memory_usage, datastore_path):
    """
    resolve_llm_field prefers the watch's own value over the tag's.
    """
    from changedetectionio.llm.evaluator import resolve_llm_field

    ds = client.application.config.get('DATASTORE')
    api_token = _api_token(client)
    test_url = url_for('test_endpoint', _external=True)

    watch_uuid = _create_watch(client, test_url, api_token)
    tag_uuid = _add_tag_with_llm(ds, 'Override Group', llm_intent='Tag intent')
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
    llm_intent can come from a group (readonly) while llm_change_summary
    is editable (watch has its own), and vice versa.
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
    )
    _link_watch_to_tag(ds, watch_uuid, tag_uuid)

    # Watch overrides only llm_change_summary
    ds.data['watching'][watch_uuid]['llm_change_summary'] = 'My own summary'

    res = client.get(url_for('ui.ui_edit.edit_page', uuid=watch_uuid))
    assert res.status_code == 200
    body = res.data.decode('utf-8', errors='replace')

    # llm_intent: group placeholder visible (watch has no own value)
    assert 'Group intent here' in body
    intent_pos = body.find('name="llm_intent"')
    assert intent_pos != -1
    intent_snippet = body[max(0, intent_pos - 50): intent_pos + 300]
    assert 'readonly' not in intent_snippet, \
        f"llm_intent must be editable even when group sets it; snippet: {intent_snippet!r}"

    # llm_change_summary: watch own value shown in body, no group placeholder
    assert 'My own summary' in body
    summary_pos = body.find('name="llm_change_summary"')
    assert summary_pos != -1
    summary_snippet = body[max(0, summary_pos - 50): summary_pos + 300]
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
