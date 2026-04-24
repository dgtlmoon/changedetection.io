#!/usr/bin/env python3
"""
Tests that verify global LLM token budget counters cannot be tampered with
via the API (watch PUT) or via form submissions (settings page POST).

This is critical for hosted deployments where the operator sets
LLM_TOKEN_BUDGET_MONTH in the container — tenants must not be able
to reset or inflate the counter themselves.
"""

import json
import os

import pytest
from flask import url_for

from changedetectionio.tests.util import live_server_setup, delete_all_watches


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_token_counters(datastore, this_month=5000, total=12000):
    """Pre-load token counters into the datastore's llm settings dict."""
    from changedetectionio.llm.evaluator import _get_month_key
    app_settings = datastore.data['settings']['application']
    if 'llm' not in app_settings:
        app_settings['llm'] = {}
    app_settings['llm'].update({
        'model': 'gpt-4o-mini',
        'api_key': 'sk-test',
        'tokens_this_month': this_month,
        'tokens_total_cumulative': total,
        'tokens_month_key': _get_month_key(),
    })


def _get_counters(datastore):
    llm_cfg = datastore.data['settings']['application'].get('llm') or {}
    return {
        'tokens_this_month': llm_cfg.get('tokens_this_month', 0),
        'tokens_total_cumulative': llm_cfg.get('tokens_total_cumulative', 0),
        'tokens_month_key': llm_cfg.get('tokens_month_key'),
    }


# ---------------------------------------------------------------------------
# API tamper tests
# ---------------------------------------------------------------------------

def test_api_cannot_reset_token_counters_via_watch_put(
        client, live_server, measure_memory_usage, datastore_path):
    """
    A PUT to /api/v1/watch/<uuid> must NOT be able to reset or change the
    global token counters stored in settings.application.llm.
    The counters live on the datastore settings, not the watch object,
    so this test confirms they remain intact regardless of API activity.
    """
    ds = client.application.config.get('DATASTORE')
    api_key = ds.data['settings']['application'].get('api_access_token')

    _seed_token_counters(ds, this_month=7000, total=20000)

    test_url = url_for('test_endpoint', _external=True)

    # Create a watch via API
    res = client.post(
        url_for("createwatch"),
        data=json.dumps({"url": test_url}),
        headers={'content-type': 'application/json', 'x-api-key': api_key},
        follow_redirects=True,
    )
    assert res.status_code == 201
    uuid = res.json.get('uuid')

    # Attempt to PUT the watch with llm_tokens_used_cumulative set to 0
    # (trying to "reset" the per-watch counter — this field is readOnly on watches,
    # but more importantly the global counters on settings must be unaffected)
    res = client.put(
        url_for("watch", uuid=uuid),
        headers={'x-api-key': api_key, 'content-type': 'application/json'},
        data=json.dumps({
            "url": test_url,
            "llm_tokens_used_cumulative": 0,   # readOnly on Watch — should be silently ignored
            "llm_last_tokens_used": 0,          # readOnly on Watch — should be silently ignored
        }),
    )
    assert res.status_code == 200, f"PUT failed: {res.data}"

    # Global counters on settings must be completely unchanged
    after = _get_counters(ds)
    assert after['tokens_this_month'] == 7000, \
        "API PUT must not reset tokens_this_month"
    assert after['tokens_total_cumulative'] == 20000, \
        "API PUT must not reset tokens_total_cumulative"

    delete_all_watches(client)


def test_api_watch_put_llm_readonly_fields_are_ignored(
        client, live_server, measure_memory_usage, datastore_path):
    """
    llm_prefilter, llm_evaluation_cache, llm_last_tokens_used,
    llm_tokens_used_cumulative are all readOnly in the API spec.
    Sending them in a PUT must not raise an error (they should be silently
    stripped) and must not modify the watch's stored values.
    """
    ds = client.application.config.get('DATASTORE')
    api_key = ds.data['settings']['application'].get('api_access_token')

    test_url = url_for('test_endpoint', _external=True)

    res = client.post(
        url_for("createwatch"),
        data=json.dumps({"url": test_url}),
        headers={'content-type': 'application/json', 'x-api-key': api_key},
        follow_redirects=True,
    )
    assert res.status_code == 201
    uuid = res.json.get('uuid')

    # Try to set readOnly LLM fields via PUT
    res = client.put(
        url_for("watch", uuid=uuid),
        headers={'x-api-key': api_key, 'content-type': 'application/json'},
        data=json.dumps({
            "url": test_url,
            "llm_tokens_used_cumulative": 999999,
            "llm_last_tokens_used": 888888,
            "llm_prefilter": "div.hacked",
            "llm_evaluation_cache": {"fake_key": {"important": True}},
        }),
    )
    # Must succeed (not 400) — readOnly fields are silently stripped
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.data}"

    # Fetch back and confirm readOnly values were NOT stored
    res = client.get(
        url_for("watch", uuid=uuid),
        headers={'x-api-key': api_key},
    )
    assert res.json.get('llm_tokens_used_cumulative') != 999999
    assert res.json.get('llm_last_tokens_used') != 888888

    delete_all_watches(client)


# ---------------------------------------------------------------------------
# Settings form tamper tests
# ---------------------------------------------------------------------------

def test_settings_form_preserves_token_counters(
        client, live_server, measure_memory_usage, datastore_path):
    """
    Submitting the settings form (POST /settings) must preserve existing
    token counters even when the LLM model/key fields change.
    A malicious or accidental form submission must not zero the counters.
    """
    ds = client.application.config.get('DATASTORE')
    _seed_token_counters(ds, this_month=3000, total=9000)

    before = _get_counters(ds)
    assert before['tokens_this_month'] == 3000

    # Submit settings form with a different model — simulates a normal settings save
    res = client.post(
        url_for('settings.settings_page'),
        data={
            # LLM sub-form fields
            'llm-llm_model': 'gpt-4o',
            'llm-llm_api_key': 'sk-different-key',
            'llm-llm_api_base': '',
            # Minimal required fields to pass form validation
            'application-pager_size': '50',
            'application-notification_format': 'System default',
            'requests-time_between_check-days': '0',
            'requests-time_between_check-hours': '0',
            'requests-time_between_check-minutes': '5',
            'requests-time_between_check-seconds': '0',
            'requests-time_between_check-weeks': '0',
            'requests-workers': '10',
            'requests-timeout': '60',
        },
        follow_redirects=True,
    )
    # Settings save may redirect; we just need it to not crash
    assert res.status_code == 200

    after = _get_counters(ds)
    assert after['tokens_this_month'] == 3000, \
        f"Settings form save must not reset tokens_this_month (got {after['tokens_this_month']})"
    assert after['tokens_total_cumulative'] == 9000, \
        f"Settings form save must not reset tokens_total_cumulative (got {after['tokens_total_cumulative']})"

    delete_all_watches(client)


def test_settings_form_cannot_inject_fake_token_counts(
        client, live_server, measure_memory_usage, datastore_path):
    """
    Even if a form POST includes hidden fields for token counters,
    those values must be ignored and the real counters must remain intact.
    """
    ds = client.application.config.get('DATASTORE')
    _seed_token_counters(ds, this_month=1500, total=4000)

    # Attempt to inject inflated or zeroed counters via form POST
    res = client.post(
        url_for('settings.settings_page'),
        data={
            'llm-llm_model': 'gpt-4o-mini',
            'llm-llm_api_key': 'sk-test',
            'llm-llm_api_base': '',
            # Attempted injection of token counter fields
            'llm-tokens_this_month': '0',
            'llm-tokens_total_cumulative': '0',
            'llm-tokens_month_key': '1970-01',
            # Minimal required fields
            'application-pager_size': '50',
            'application-notification_format': 'System default',
            'requests-time_between_check-days': '0',
            'requests-time_between_check-hours': '0',
            'requests-time_between_check-minutes': '5',
            'requests-time_between_check-seconds': '0',
            'requests-time_between_check-weeks': '0',
            'requests-workers': '10',
            'requests-timeout': '60',
        },
        follow_redirects=True,
    )
    assert res.status_code == 200

    after = _get_counters(ds)
    assert after['tokens_this_month'] == 1500, \
        f"Form injection must not alter tokens_this_month (got {after['tokens_this_month']})"
    assert after['tokens_total_cumulative'] == 4000, \
        f"Form injection must not alter tokens_total_cumulative (got {after['tokens_total_cumulative']})"

    delete_all_watches(client)


# ---------------------------------------------------------------------------
# accumulate_global_tokens unit tests
# ---------------------------------------------------------------------------

def test_accumulate_global_tokens_month_rollover(
        client, live_server, measure_memory_usage, datastore_path):
    """
    When tokens_month_key is stale (different month), tokens_this_month
    must reset to zero before accumulating, and the key must update.
    """
    from changedetectionio.llm.evaluator import accumulate_global_tokens, _get_month_key
    from unittest.mock import patch

    ds = client.application.config.get('DATASTORE')
    ds.data['settings']['application']['llm'] = {
        'model': 'gpt-4o-mini',
        'tokens_this_month': 500,
        'tokens_total_cumulative': 1000,
        'tokens_month_key': '2024-01',  # stale — previous month
    }

    # accumulate_global_tokens must detect the rollover and reset the monthly counter
    accumulate_global_tokens(ds, 100)

    llm_cfg = ds.data['settings']['application']['llm']
    assert llm_cfg['tokens_month_key'] == _get_month_key(), "Month key must be current"
    assert llm_cfg['tokens_this_month'] == 100, \
        "Monthly counter must reset on rollover, then add new tokens"
    assert llm_cfg['tokens_total_cumulative'] == 1100, \
        "All-time counter must never reset"

    delete_all_watches(client)


def test_accumulate_global_tokens_same_month(
        client, live_server, measure_memory_usage, datastore_path):
    """Within the same month, both counters accumulate additively."""
    from changedetectionio.llm.evaluator import accumulate_global_tokens, _get_month_key

    ds = client.application.config.get('DATASTORE')
    current_month = _get_month_key()
    ds.data['settings']['application']['llm'] = {
        'model': 'gpt-4o-mini',
        'tokens_this_month': 200,
        'tokens_total_cumulative': 800,
        'tokens_month_key': current_month,
    }

    accumulate_global_tokens(ds, 50)

    llm_cfg = ds.data['settings']['application']['llm']
    assert llm_cfg['tokens_this_month'] == 250
    assert llm_cfg['tokens_total_cumulative'] == 850

    delete_all_watches(client)


def test_is_global_token_budget_exceeded(
        client, live_server, measure_memory_usage, datastore_path):
    """is_global_token_budget_exceeded returns True only when budget is set and reached."""
    from changedetectionio.llm.evaluator import is_global_token_budget_exceeded, _get_month_key

    ds = client.application.config.get('DATASTORE')
    current_month = _get_month_key()

    # No budget env var → never exceeded
    with pytest.MonkeyPatch().context() as mp:
        mp.delenv('LLM_TOKEN_BUDGET_MONTH', raising=False)
        ds.data['settings']['application']['llm'] = {
            'tokens_this_month': 999999,
            'tokens_month_key': current_month,
        }
        assert not is_global_token_budget_exceeded(ds)

    # Budget set, under limit
    with pytest.MonkeyPatch().context() as mp:
        mp.setenv('LLM_TOKEN_BUDGET_MONTH', '10000')
        ds.data['settings']['application']['llm'] = {
            'tokens_this_month': 5000,
            'tokens_month_key': current_month,
        }
        assert not is_global_token_budget_exceeded(ds)

    # Budget set, at limit (exact)
    with pytest.MonkeyPatch().context() as mp:
        mp.setenv('LLM_TOKEN_BUDGET_MONTH', '10000')
        ds.data['settings']['application']['llm'] = {
            'tokens_this_month': 10000,
            'tokens_month_key': current_month,
        }
        assert is_global_token_budget_exceeded(ds)

    # Budget set, over limit
    with pytest.MonkeyPatch().context() as mp:
        mp.setenv('LLM_TOKEN_BUDGET_MONTH', '10000')
        ds.data['settings']['application']['llm'] = {
            'tokens_this_month': 12345,
            'tokens_month_key': current_month,
        }
        assert is_global_token_budget_exceeded(ds)

    # Budget set but stale month key → counter is 0 for current month → not exceeded
    with pytest.MonkeyPatch().context() as mp:
        mp.setenv('LLM_TOKEN_BUDGET_MONTH', '100')
        ds.data['settings']['application']['llm'] = {
            'tokens_this_month': 9999,
            'tokens_month_key': '2020-01',  # stale
        }
        assert not is_global_token_budget_exceeded(ds)

    delete_all_watches(client)


# ---------------------------------------------------------------------------
# Cost accumulation tests
# ---------------------------------------------------------------------------

def test_accumulate_global_tokens_tracks_cost_for_known_model(
        client, live_server, measure_memory_usage, datastore_path):
    """
    When input/output tokens and a known model are supplied, cost_usd_this_month
    and cost_usd_total_cumulative must be accumulated as positive floats.
    Uses litellm's real pricing db — exact value may change but must be > 0
    for a model that has known pricing (gpt-4o-mini).
    """
    from changedetectionio.llm.evaluator import accumulate_global_tokens, _get_month_key

    ds = client.application.config.get('DATASTORE')
    ds.data['settings']['application']['llm'] = {
        'model': 'gpt-4o-mini',
        'tokens_this_month': 0,
        'tokens_total_cumulative': 0,
        'tokens_month_key': _get_month_key(),
        'cost_usd_this_month': 0.0,
        'cost_usd_total_cumulative': 0.0,
    }

    accumulate_global_tokens(ds, tokens=1000, input_tokens=800, output_tokens=200, model='gpt-4o-mini')

    llm_cfg = ds.data['settings']['application']['llm']
    assert llm_cfg['tokens_this_month'] == 1000
    assert llm_cfg['tokens_total_cumulative'] == 1000
    # gpt-4o-mini has known pricing in litellm — cost must be > 0
    assert llm_cfg.get('cost_usd_this_month', 0) > 0, \
        "cost_usd_this_month must be positive for a model with known pricing"
    assert llm_cfg.get('cost_usd_total_cumulative', 0) > 0

    delete_all_watches(client)


def test_accumulate_global_tokens_cost_rollover(
        client, live_server, measure_memory_usage, datastore_path):
    """
    On month rollover, cost_usd_this_month must reset to zero (fresh month),
    while cost_usd_total_cumulative keeps growing.
    """
    from changedetectionio.llm.evaluator import accumulate_global_tokens, _get_month_key

    ds = client.application.config.get('DATASTORE')
    ds.data['settings']['application']['llm'] = {
        'model': 'gpt-4o-mini',
        'tokens_this_month': 500,
        'tokens_total_cumulative': 1000,
        'tokens_month_key': '2024-01',  # stale month
        'cost_usd_this_month': 0.05,
        'cost_usd_total_cumulative': 0.20,
    }

    accumulate_global_tokens(ds, tokens=50, input_tokens=40, output_tokens=10, model='gpt-4o-mini')

    llm_cfg = ds.data['settings']['application']['llm']
    assert llm_cfg['tokens_month_key'] == _get_month_key(), "Month key must update"
    assert llm_cfg['tokens_this_month'] == 50, "Monthly token counter must reset then add"
    assert llm_cfg['tokens_total_cumulative'] == 1050, "All-time counter must not reset"
    # Monthly cost must reset (old 0.05 discarded) then add new cost
    assert llm_cfg['cost_usd_this_month'] >= 0.0
    assert llm_cfg['cost_usd_this_month'] < 0.05, \
        "Monthly cost must have reset (new cost for 50 tokens is less than old 0.05)"
    # All-time cost must keep growing from 0.20
    assert llm_cfg['cost_usd_total_cumulative'] >= 0.20

    delete_all_watches(client)


def test_accumulate_global_tokens_no_cost_for_unknown_model(
        client, live_server, measure_memory_usage, datastore_path):
    """
    When model is unknown (e.g. custom endpoint) or no input/output split
    is provided, cost stays at 0.0 — no error raised.
    """
    from changedetectionio.llm.evaluator import accumulate_global_tokens, _get_month_key

    ds = client.application.config.get('DATASTORE')
    ds.data['settings']['application']['llm'] = {
        'tokens_this_month': 0,
        'tokens_total_cumulative': 0,
        'tokens_month_key': _get_month_key(),
        'cost_usd_this_month': 0.0,
        'cost_usd_total_cumulative': 0.0,
    }

    # No model, no input/output split → no cost
    accumulate_global_tokens(ds, tokens=200)

    llm_cfg = ds.data['settings']['application']['llm']
    assert llm_cfg['tokens_this_month'] == 200
    assert llm_cfg['cost_usd_this_month'] == 0.0
    assert llm_cfg['cost_usd_total_cumulative'] == 0.0

    delete_all_watches(client)


def test_cost_fields_are_tamper_proof_via_settings_form(
        client, live_server, measure_memory_usage, datastore_path):
    """
    Submitting the settings form must not be able to set cost_usd_this_month
    or cost_usd_total_cumulative — those are operator-controlled counters.
    """
    from flask import url_for

    ds = client.application.config.get('DATASTORE')
    ds.data['settings']['application']['llm'] = {
        'model': 'gpt-4o-mini',
        'api_key': 'sk-test',
        'cost_usd_this_month': 1.23,
        'cost_usd_total_cumulative': 9.99,
    }

    client.post(
        url_for('settings.settings_page'),
        data={
            'llm-llm_model': 'gpt-4o',
            'llm-llm_api_key': 'sk-test',
            'llm-llm_api_base': '',
            'llm-cost_usd_this_month': '0',       # injection attempt
            'llm-cost_usd_total_cumulative': '0',  # injection attempt
            'application-pager_size': '50',
            'application-notification_format': 'System default',
            'requests-time_between_check-days': '0',
            'requests-time_between_check-hours': '0',
            'requests-time_between_check-minutes': '5',
            'requests-time_between_check-seconds': '0',
            'requests-time_between_check-weeks': '0',
            'requests-workers': '10',
            'requests-timeout': '60',
        },
        follow_redirects=True,
    )

    llm_cfg = ds.data['settings']['application'].get('llm', {})
    assert llm_cfg.get('cost_usd_this_month') == 1.23, \
        "cost_usd_this_month must be tamper-proof"
    assert llm_cfg.get('cost_usd_total_cumulative') == 9.99, \
        "cost_usd_total_cumulative must be tamper-proof"

    delete_all_watches(client)
