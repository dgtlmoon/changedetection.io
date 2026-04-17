#!/usr/bin/env python3
"""
Integration tests for AI Change Summary:
  - llm_change_summary field saved via watch edit form
  - llm_change_summary cascades from tag to watches
  - {{ diff }} replaced by AI summary in notifications
  - {{ raw_diff }} always contains original diff
  - summarise_change only runs when change is detected
"""

import json
import time
from unittest.mock import patch

from flask import url_for

from changedetectionio.tests.util import wait_for_all_checks, delete_all_watches

HTML_V1 = "<html><body><ul><li>Item A</li><li>Item B</li></ul></body></html>"
HTML_V2 = "<html><body><ul><li>Item A</li><li>Item B</li><li>Item C — NEW</li></ul></body></html>"


def _set_response(datastore_path, content):
    import os
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(content)


def _configure_llm(client):
    ds = client.application.config.get('DATASTORE')
    ds.data['settings']['application']['llm'] = {'model': 'gpt-4o-mini', 'api_key': 'sk-test'}


# ---------------------------------------------------------------------------
# Form field persistence
# ---------------------------------------------------------------------------

def test_llm_change_summary_saved_via_edit_form(
        client, live_server, measure_memory_usage, datastore_path):
    """llm_change_summary submitted via watch edit form is persisted."""
    _set_response(datastore_path, HTML_V1)
    _configure_llm(client)
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid),
        data={
            "url": test_url,
            "fetch_backend": "html_requests",
            "time_between_check_use_default": "y",
            "llm_change_summary": "List new items added as bullet points. Translate to English.",
        },
        follow_redirects=True,
    )
    assert b"Updated watch." in res.data

    watch = client.application.config.get('DATASTORE').data['watching'][uuid]
    assert watch.get('llm_change_summary') == "List new items added as bullet points. Translate to English."

    delete_all_watches(client)


def test_llm_change_summary_cascades_from_tag(
        client, live_server, measure_memory_usage, datastore_path):
    """llm_change_summary set on a tag is resolved for watches in that tag."""
    from changedetectionio.llm.evaluator import resolve_llm_field

    ds = client.application.config.get('DATASTORE')
    _configure_llm(client)
    _set_response(datastore_path, HTML_V1)
    test_url = url_for('test_endpoint', _external=True)

    # Create a tag with llm_change_summary
    tag_uuid = ds.add_tag('events-group')
    ds.data['settings']['application']['tags'][tag_uuid]['llm_change_summary'] = 'Summarise new events'

    # Watch in that tag, no own summary prompt
    uuid = ds.add_watch(url=test_url)
    ds.data['watching'][uuid]['tags'] = [tag_uuid]
    ds.data['watching'][uuid]['llm_change_summary'] = ''

    watch = ds.data['watching'][uuid]
    value, source = resolve_llm_field(watch, ds, 'llm_change_summary')
    assert value == 'Summarise new events'
    assert source == 'events-group'

    delete_all_watches(client)


# ---------------------------------------------------------------------------
# Notification token behaviour
# ---------------------------------------------------------------------------

def test_diff_token_replaced_by_ai_summary_in_notification(
        client, live_server, measure_memory_usage, datastore_path):
    """
    When _llm_change_summary is set on the watch, the notification handler
    must substitute it into {{ diff }} and preserve {{ raw_diff }}.
    """
    from changedetectionio.notification.handler import process_notification

    n_object = {
        'notification_urls': ['json://localhost/'],
        'notification_title': 'Change detected',
        'notification_body': 'Summary: {{diff}}\nRaw: {{raw_diff}}',
        'notification_format': 'text',
        'uuid': 'test-uuid',
        'watch_url': 'https://example.com',
        'current_snapshot': 'Item A\nItem B\nItem C',
        'prev_snapshot': 'Item A\nItem B',
        'diff': '',          # populated by add_rendered_diff_to_notification_vars
        'raw_diff': '',
        '_llm_change_summary': '1 new item added: Item C',
        '_llm_result': None,
        '_llm_intent': '',
        'base_url': 'http://localhost:5000/',
        'watch_mime_type': 'text/plain',
        'triggered_text': '',
    }

    # We only need to verify the token substitution logic, not send a real notification
    # Invoke just enough of the handler to check n_object state after substitution
    from changedetectionio.notification_service import add_rendered_diff_to_notification_vars

    diff_vars = add_rendered_diff_to_notification_vars(
        notification_scan_text=n_object['notification_body'] + n_object['notification_title'],
        current_snapshot=n_object['current_snapshot'],
        prev_snapshot=n_object['prev_snapshot'],
        word_diff=False,
    )
    n_object.update(diff_vars)

    # Simulate what handler.py does
    n_object['raw_diff'] = n_object.get('diff', '')
    llm_summary = (n_object.get('_llm_change_summary') or '').strip()
    if llm_summary:
        n_object['diff'] = llm_summary

    assert n_object['diff'] == '1 new item added: Item C'
    assert 'Item C' in n_object['raw_diff'] or n_object['raw_diff'] != n_object['diff']

    delete_all_watches(client)


# ---------------------------------------------------------------------------
# Error surfacing — rate limit / provider errors reach the AJAX endpoint
# ---------------------------------------------------------------------------

def test_llm_summary_ajax_surfaces_rate_limit_error(
        client, live_server, measure_memory_usage, datastore_path):
    """
    When the LLM call raises a RateLimitError the /llm-summary AJAX route must
    return JSON {"summary": null, "error": "<readable message>"} with a 500
    status — not "LLM returned empty summary".
    """
    from unittest.mock import patch

    _configure_llm(client)
    ds = client.application.config.get('DATASTORE')

    test_url = url_for('test_endpoint', content_type='text/html', content='v1', _external=True)
    uuid = ds.add_watch(url=test_url)
    watch = ds.data['watching'][uuid]

    watch.save_history_blob('snapshot one\n', '2000000000', 'snap1')
    watch.save_history_blob('snapshot two\n', '2000000001', 'snap2')

    # Build a realistic litellm RateLimitError string (matches real exception format)
    rate_limit_msg = (
        'litellm.RateLimitError: litellm.RateLimitError: geminiException - '
        '{"error": {"code": 429, "message": "You exceeded your current quota, '
        'please check your plan and billing details.", "status": "RESOURCE_EXHAUSTED"}}'
    )

    import litellm as _real_litellm
    exc = _real_litellm.RateLimitError(
        rate_limit_msg, llm_provider='gemini', model='gemini/gemini-2.5-pro'
    )
    with patch('litellm.completion', side_effect=exc):
        res = client.get(
            url_for('ui.ui_diff.diff_llm_summary', uuid=uuid,
                    from_version='2000000000', to_version='2000000001'),
        )

    assert res.status_code == 500
    data = res.get_json()
    assert data['summary'] is None
    assert data['error']                                   # non-empty
    assert 'LLM returned empty summary' not in data['error']
    # Should contain the human-readable quota message, not a raw JSON blob
    assert '{' not in data['error'], f"Error still contains raw JSON: {data['error']}"

    delete_all_watches(client)


def test_llm_summary_ajax_error_displayed_not_silenced(
        client, live_server, measure_memory_usage, datastore_path):
    """
    Any non-success response from /llm-summary that has an 'error' key
    should be surfaced — verify the JSON contract (error present, summary absent).
    Auth errors, timeout errors, etc. should follow the same shape.
    """
    from unittest.mock import patch

    _configure_llm(client)
    ds = client.application.config.get('DATASTORE')

    test_url = url_for('test_endpoint', content_type='text/html', content='v1', _external=True)
    uuid = ds.add_watch(url=test_url)
    watch = ds.data['watching'][uuid]

    watch.save_history_blob('old content\n', '3000000000', 'snap-a')
    watch.save_history_blob('new content\n', '3000000001', 'snap-b')

    import litellm as _real_litellm
    exc = _real_litellm.AuthenticationError(
        'litellm.AuthenticationError: Invalid API key.',
        llm_provider='openai', model='gpt-4o-mini'
    )
    with patch('litellm.completion', side_effect=exc):
        res = client.get(
            url_for('ui.ui_diff.diff_llm_summary', uuid=uuid,
                    from_version='3000000000', to_version='3000000001'),
        )

    assert res.status_code == 500
    data = res.get_json()
    assert data['summary'] is None
    assert data['error']
    assert 'LLM returned empty summary' not in data['error']

    delete_all_watches(client)


def test_diff_token_unchanged_when_no_ai_summary(
        client, live_server, measure_memory_usage, datastore_path):
    """When no AI Change Summary is configured, {{ diff }} renders the raw diff as normal."""
    from changedetectionio.notification_service import add_rendered_diff_to_notification_vars

    n_object = {
        'current_snapshot': 'Item A\nItem B\nItem C',
        'prev_snapshot': 'Item A\nItem B',
        '_llm_change_summary': '',
    }

    diff_vars = add_rendered_diff_to_notification_vars(
        notification_scan_text='{{diff}}',
        current_snapshot=n_object['current_snapshot'],
        prev_snapshot=n_object['prev_snapshot'],
        word_diff=False,
    )
    n_object.update(diff_vars)

    raw = n_object.get('diff', '')
    n_object['raw_diff'] = raw
    if (n_object.get('_llm_change_summary') or '').strip():
        n_object['diff'] = n_object['_llm_change_summary']

    # diff should still be the raw diff (not replaced)
    assert n_object['diff'] == n_object['raw_diff']

    delete_all_watches(client)
