#!/usr/bin/env python3
"""
Tests for the 'AI: every change between versions' (all_changes=1) feature.

Covers:
  - all_changes=1 builds a multi-segment diff (pairwise across intermediate snapshots)
  - all_changes=0 (default) uses a single from→to diff
  - the two modes are cached under separate keys (no cross-contamination)
  - a repeated all_changes=1 call returns the cached result without re-calling the LLM
"""

from unittest.mock import patch, call

from flask import url_for

from changedetectionio.tests.util import delete_all_watches


SNAP1 = "apple\nbanana\n"
SNAP2 = "apple\nbanana\ncherry\n"
SNAP3 = "apple\nbanana\ncherry\ndate\n"

TS1 = "2000000001"
TS2 = "2000000002"
TS3 = "2000000003"


def _configure_llm(client):
    ds = client.application.config.get('DATASTORE')
    ds.data['settings']['application']['llm'] = {'model': 'gpt-4o-mini', 'api_key': 'sk-test'}


def _make_watch_with_three_snapshots(client):
    ds = client.application.config.get('DATASTORE')
    uuid = ds.add_watch(url='https://example.com/allchanges')
    watch = ds.data['watching'][uuid]
    watch.save_history_blob(SNAP1, TS1, 'snap1')
    watch.save_history_blob(SNAP2, TS2, 'snap2')
    watch.save_history_blob(SNAP3, TS3, 'snap3')
    return uuid, watch


# ---------------------------------------------------------------------------
# Multi-segment diff content reaches the LLM
# ---------------------------------------------------------------------------

def test_all_changes_sends_multi_segment_diff_to_llm(
        client, live_server, measure_memory_usage, datastore_path):
    """
    With all_changes=1 the diff passed to summarise_change must contain
    two pairwise segments (TS1→TS2 and TS2→TS3), not just a single diff.
    """
    _configure_llm(client)
    uuid, _ = _make_watch_with_three_snapshots(client)

    captured_diff = {}

    def fake_summarise(watch, datastore, diff, current_snapshot=None):
        captured_diff['diff'] = diff
        return 'Multi-step summary.'

    with patch('changedetectionio.llm.evaluator.summarise_change', side_effect=fake_summarise):
        res = client.get(url_for(
            'ui.ui_diff.diff_llm_summary', uuid=uuid,
            from_version=TS1, to_version=TS3, all_changes=1,
        ))

    assert res.status_code == 200
    data = res.get_json()
    assert data['summary'] == 'Multi-step summary.'
    assert data['error'] is None

    diff_sent = captured_diff.get('diff', '')
    # Both segment headers must be present
    assert f'{TS1} \u2192 {TS2}' in diff_sent, f"Missing TS1→TS2 header in: {diff_sent!r}"
    assert f'{TS2} \u2192 {TS3}' in diff_sent, f"Missing TS2→TS3 header in: {diff_sent!r}"

    delete_all_watches(client)


# ---------------------------------------------------------------------------
# Single-range diff (all_changes=0, the default)
# ---------------------------------------------------------------------------

def test_default_mode_sends_single_diff_to_llm(
        client, live_server, measure_memory_usage, datastore_path):
    """
    With all_changes=0 (or omitted) summarise_change receives a plain
    unified diff between from_version and to_version only — no segment headers.
    """
    _configure_llm(client)
    uuid, _ = _make_watch_with_three_snapshots(client)

    captured_diff = {}

    def fake_summarise(watch, datastore, diff, current_snapshot=None):
        captured_diff['diff'] = diff
        return 'Single-range summary.'

    with patch('changedetectionio.llm.evaluator.summarise_change', side_effect=fake_summarise):
        res = client.get(url_for(
            'ui.ui_diff.diff_llm_summary', uuid=uuid,
            from_version=TS1, to_version=TS3, all_changes=0,
        ))

    assert res.status_code == 200
    diff_sent = captured_diff.get('diff', '')
    assert '\u2192' not in diff_sent, "Segment headers should not appear in single-range mode"

    delete_all_watches(client)


# ---------------------------------------------------------------------------
# Cache key separation: all_changes=1 and all_changes=0 don't share cache
# ---------------------------------------------------------------------------

def test_all_changes_and_direct_use_separate_cache_keys(
        client, live_server, measure_memory_usage, datastore_path):
    """
    A cached all_changes=1 summary must not be served for an all_changes=0
    request on the same from/to pair, and vice-versa.
    """
    _configure_llm(client)
    uuid, _ = _make_watch_with_three_snapshots(client)

    call_count = {'n': 0}

    def fake_summarise(watch, datastore, diff, current_snapshot=None):
        call_count['n'] += 1
        return f'Summary call #{call_count["n"]}'

    with patch('changedetectionio.llm.evaluator.summarise_change', side_effect=fake_summarise):
        # First call: all_changes=1
        r1 = client.get(url_for(
            'ui.ui_diff.diff_llm_summary', uuid=uuid,
            from_version=TS1, to_version=TS3, all_changes=1,
        ))
        # Second call: all_changes=0 — must NOT hit the cache from above
        r2 = client.get(url_for(
            'ui.ui_diff.diff_llm_summary', uuid=uuid,
            from_version=TS1, to_version=TS3, all_changes=0,
        ))

    assert call_count['n'] == 2, "LLM should be called twice (separate cache keys)"
    assert r1.get_json()['summary'] != r2.get_json()['summary']

    delete_all_watches(client)


# ---------------------------------------------------------------------------
# Caching: second all_changes=1 call returns cached result
# ---------------------------------------------------------------------------

def test_all_changes_result_is_cached(
        client, live_server, measure_memory_usage, datastore_path):
    """
    A second all_changes=1 request for the same from/to pair must be
    served from cache — summarise_change must only be called once.
    """
    _configure_llm(client)
    uuid, _ = _make_watch_with_three_snapshots(client)

    call_count = {'n': 0}

    def fake_summarise(watch, datastore, diff, current_snapshot=None):
        call_count['n'] += 1
        return 'Cached multi-step summary.'

    with patch('changedetectionio.llm.evaluator.summarise_change', side_effect=fake_summarise):
        r1 = client.get(url_for(
            'ui.ui_diff.diff_llm_summary', uuid=uuid,
            from_version=TS1, to_version=TS3, all_changes=1,
        ))
        r2 = client.get(url_for(
            'ui.ui_diff.diff_llm_summary', uuid=uuid,
            from_version=TS1, to_version=TS3, all_changes=1,
        ))

    assert call_count['n'] == 1, "LLM should only be called once; second request should be cached"
    assert r1.get_json()['summary'] == r2.get_json()['summary'] == 'Cached multi-step summary.'
    assert r2.get_json().get('cached') is True

    delete_all_watches(client)
