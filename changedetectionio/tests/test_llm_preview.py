#!/usr/bin/env python3
"""
Integration tests: /edit/<uuid>/preview-rendered returns llm_evaluation when
llm_intent is submitted alongside the filter form data.

These tests verify the full backend path:
  JS POSTs llm_intent → prepare_filter_prevew() applies it to tmp_watch
  → preview_extract() is called → llm_evaluation appears in JSON response

The response uses {'found': bool, 'answer': str} — NOT the diff-evaluation
{'important', 'summary'} shape, because preview asks the LLM to extract from
the current content directly (e.g. "30 articles listed") rather than compare
a diff.
"""

import json
import time
from unittest.mock import patch

from flask import url_for

from changedetectionio.tests.util import wait_for_all_checks, delete_all_watches


HTML_WITH_ARTICLES = """<html><body>
<ul id="articles">
  <li>Article One</li>
  <li>Article Two</li>
  <li>Article Three</li>
</ul>
</body></html>"""

HTML_WITH_PRICE = """<html><body>
<p class="price">Original price: $199.00</p>
<p class="discount">Now: $149.00 — 25% off!</p>
</body></html>"""


def _set_response(datastore_path, content):
    import os
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(content)


def _add_and_fetch(client, live_server, datastore_path, html):
    """Add a watch, fetch it once so a snapshot exists, return uuid."""
    _set_response(datastore_path, html)
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    time.sleep(0.5)
    wait_for_all_checks(client)
    return uuid


def _configure_llm(client):
    """Put a fake LLM config into the datastore."""
    datastore = client.application.config.get('DATASTORE')
    datastore.data['settings']['application']['llm'] = {
        'model': 'gpt-4o-mini',
        'api_key': 'sk-test-fake',
    }


# ---------------------------------------------------------------------------
# llm_intent submitted → llm_evaluation returned with found/answer shape
# ---------------------------------------------------------------------------

def test_preview_returns_llm_answer_for_article_intent(
        client, live_server, measure_memory_usage, datastore_path):
    """
    With llm_intent='Tell me the number of articles in the list',
    the preview endpoint returns llm_evaluation with found=True and an answer
    that directly addresses the intent (e.g. "3 articles listed").
    """
    uuid = _add_and_fetch(client, live_server, datastore_path, HTML_WITH_ARTICLES)
    _configure_llm(client)

    llm_json = '{"found": true, "answer": "3 articles are listed in the content"}'
    with patch('changedetectionio.llm.client.completion', return_value=(llm_json, 50)):
        res = client.post(
            url_for("ui.ui_edit.watch_get_preview_rendered", uuid=uuid),
            data={
                'llm_intent': 'Tell me the number of articles in the list',
                'fetch_backend': 'html_requests',
            },
        )

    assert res.status_code == 200
    data = json.loads(res.data.decode('utf-8'))

    # Filtered text must still be present
    assert data.get('after_filter'), "after_filter must be present"

    # LLM evaluation must be returned with the new shape
    ev = data.get('llm_evaluation')
    assert ev is not None, "llm_evaluation must be in response"
    assert ev['found'] is True
    assert '3' in ev['answer']

    delete_all_watches(client)


def test_preview_returns_llm_answer_for_price_intent(
        client, live_server, measure_memory_usage, datastore_path):
    """
    With a price-change intent, the LLM answer should reflect the discount
    extracted directly from the current page (not a diff comparison).
    """
    uuid = _add_and_fetch(client, live_server, datastore_path, HTML_WITH_PRICE)
    _configure_llm(client)

    llm_json = '{"found": true, "answer": "Price $149, 25% off (was $199)"}'
    with patch('changedetectionio.llm.client.completion', return_value=(llm_json, 60)):
        res = client.post(
            url_for("ui.ui_edit.watch_get_preview_rendered", uuid=uuid),
            data={
                'llm_intent': 'Flag any price change, including discount percentages',
                'fetch_backend': 'html_requests',
            },
        )

    assert res.status_code == 200
    data = json.loads(res.data.decode('utf-8'))
    ev = data.get('llm_evaluation')
    assert ev is not None
    assert ev['found'] is True
    assert '25' in ev['answer'] or '149' in ev['answer']

    delete_all_watches(client)


def test_preview_found_false_when_content_not_relevant(
        client, live_server, measure_memory_usage, datastore_path):
    """found=False when the LLM determines page content doesn't match intent."""
    uuid = _add_and_fetch(client, live_server, datastore_path, HTML_WITH_ARTICLES)
    _configure_llm(client)

    llm_json = '{"found": false, "answer": "No price information found on this page"}'
    with patch('changedetectionio.llm.client.completion', return_value=(llm_json, 45)):
        res = client.post(
            url_for("ui.ui_edit.watch_get_preview_rendered", uuid=uuid),
            data={
                'llm_intent': 'Show me any product prices',
                'fetch_backend': 'html_requests',
            },
        )

    assert res.status_code == 200
    data = json.loads(res.data.decode('utf-8'))
    ev = data.get('llm_evaluation')
    assert ev is not None
    assert ev['found'] is False
    assert ev['answer']

    delete_all_watches(client)


# ---------------------------------------------------------------------------
# No intent / no LLM → llm_evaluation is None
# ---------------------------------------------------------------------------

def test_preview_no_llm_evaluation_without_intent(
        client, live_server, measure_memory_usage, datastore_path):
    """When llm_intent is absent, the LLM client must not be called."""
    uuid = _add_and_fetch(client, live_server, datastore_path, HTML_WITH_ARTICLES)
    _configure_llm(client)

    with patch('changedetectionio.llm.client.completion') as mock_llm:
        res = client.post(
            url_for("ui.ui_edit.watch_get_preview_rendered", uuid=uuid),
            data={'fetch_backend': 'html_requests'},
        )
        mock_llm.assert_not_called()

    assert res.status_code == 200
    data = json.loads(res.data.decode('utf-8'))
    assert data.get('llm_evaluation') is None

    delete_all_watches(client)


def test_preview_no_llm_evaluation_when_llm_not_configured(
        client, live_server, measure_memory_usage, datastore_path):
    """When LLM model is not set, llm_evaluation must be None even with an intent."""
    uuid = _add_and_fetch(client, live_server, datastore_path, HTML_WITH_ARTICLES)
    # Intentionally do NOT configure LLM

    with patch('changedetectionio.llm.client.completion') as mock_llm:
        res = client.post(
            url_for("ui.ui_edit.watch_get_preview_rendered", uuid=uuid),
            data={
                'llm_intent': 'Tell me the number of articles',
                'fetch_backend': 'html_requests',
            },
        )
        mock_llm.assert_not_called()

    assert res.status_code == 200
    data = json.loads(res.data.decode('utf-8'))
    assert data.get('llm_evaluation') is None

    delete_all_watches(client)


# ---------------------------------------------------------------------------
# LLM failure → llm_evaluation is None, preview still works
# ---------------------------------------------------------------------------

def test_preview_llm_failure_does_not_break_preview(
        client, live_server, measure_memory_usage, datastore_path):
    """If the LLM call raises, preview_extract returns None — preview still works."""
    uuid = _add_and_fetch(client, live_server, datastore_path, HTML_WITH_ARTICLES)
    _configure_llm(client)

    with patch('changedetectionio.llm.client.completion', side_effect=Exception('API timeout')):
        res = client.post(
            url_for("ui.ui_edit.watch_get_preview_rendered", uuid=uuid),
            data={
                'llm_intent': 'Tell me the number of articles',
                'fetch_backend': 'html_requests',
            },
        )

    assert res.status_code == 200
    data = json.loads(res.data.decode('utf-8'))
    # Filter content must still be returned
    assert data.get('after_filter')
    # preview_extract returns None on error (doesn't fail-open like evaluate_change)
    assert data.get('llm_evaluation') is None

    delete_all_watches(client)
