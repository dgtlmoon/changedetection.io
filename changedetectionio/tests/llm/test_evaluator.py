"""
Unit tests for changedetectionio/llm/evaluator.py

Uses mocked LLM calls — no real API key needed.
"""
import pytest
from unittest.mock import patch, MagicMock


def _make_datastore(llm_cfg=None, tags=None):
    """Build a minimal datastore-like dict for testing."""
    ds = MagicMock()
    app_settings = {
        'llm': llm_cfg or {},
        'tags': tags or {},
    }
    ds.data = {
        'settings': {
            'application': app_settings,
        }
    }
    return ds


def _make_watch(llm_intent='', tags=None, uuid='test-uuid-1234'):
    w = {}
    w['llm_intent'] = llm_intent
    w['tags'] = tags or []
    w['uuid'] = uuid
    w['url'] = 'https://example.com'
    w['page_title'] = 'Test Page'
    w['llm_evaluation_cache'] = {}
    w['llm_prefilter'] = None
    return w


# ---------------------------------------------------------------------------
# resolve_intent
# ---------------------------------------------------------------------------

class TestResolveIntent:
    def test_watch_intent_takes_priority(self):
        from changedetectionio.llm.evaluator import resolve_intent

        tag = {'title': 'mygroup', 'llm_intent': 'group intent'}
        ds = _make_datastore(tags={'tag-1': tag})
        watch = _make_watch(llm_intent='watch intent', tags=['tag-1'])

        intent, source = resolve_intent(watch, ds)
        assert intent == 'watch intent'
        assert source == 'watch'

    def test_tag_intent_used_when_watch_has_none(self):
        from changedetectionio.llm.evaluator import resolve_intent

        tag = {'title': 'pricing-group', 'llm_intent': 'flag price drops'}
        ds = _make_datastore(tags={'tag-1': tag})
        watch = _make_watch(llm_intent='', tags=['tag-1'])

        intent, source = resolve_intent(watch, ds)
        assert intent == 'flag price drops'
        assert source == 'pricing-group'

    def test_no_intent_anywhere_returns_empty(self):
        from changedetectionio.llm.evaluator import resolve_intent

        ds = _make_datastore()
        watch = _make_watch(llm_intent='')

        intent, source = resolve_intent(watch, ds)
        assert intent == ''
        assert source == ''

    def test_tag_applied_to_all_watches_in_group(self):
        """Tag intent propagates to every watch in the tag (no opt-in needed)."""
        from changedetectionio.llm.evaluator import resolve_intent

        tag = {'title': 'job-board', 'llm_intent': 'new engineering jobs'}
        ds = _make_datastore(tags={'tag-1': tag})

        # Three different watches, all in the tag, none have their own intent
        for watch_uuid in ['uuid-A', 'uuid-B', 'uuid-C']:
            watch = _make_watch(llm_intent='', tags=['tag-1'], uuid=watch_uuid)
            intent, source = resolve_intent(watch, ds)
            assert intent == 'new engineering jobs', f"Watch {watch_uuid} should inherit tag intent"
            assert source == 'job-board'

    def test_whitespace_only_intent_treated_as_empty(self):
        from changedetectionio.llm.evaluator import resolve_intent

        ds = _make_datastore()
        watch = _make_watch(llm_intent='   ')
        intent, source = resolve_intent(watch, ds)
        assert intent == ''

    def test_missing_tag_in_datastore_skipped(self):
        from changedetectionio.llm.evaluator import resolve_intent

        ds = _make_datastore(tags={})  # no tags registered
        watch = _make_watch(llm_intent='', tags=['nonexistent-tag'])
        intent, source = resolve_intent(watch, ds)
        assert intent == ''


# ---------------------------------------------------------------------------
# get_llm_config
# ---------------------------------------------------------------------------

class TestGetLlmConfig:
    def test_returns_none_when_no_model(self):
        from changedetectionio.llm.evaluator import get_llm_config
        ds = _make_datastore(llm_cfg={})
        assert get_llm_config(ds) is None

    def test_returns_config_when_model_set(self):
        from changedetectionio.llm.evaluator import get_llm_config
        cfg = {'model': 'gpt-4o-mini', 'api_key': 'sk-test'}
        ds = _make_datastore(llm_cfg=cfg)
        result = get_llm_config(ds)
        assert result['model'] == 'gpt-4o-mini'

    def test_env_var_overrides_datastore(self):
        """LLM_MODEL env var takes priority over datastore settings."""
        from changedetectionio.llm.evaluator import get_llm_config
        ds = _make_datastore(llm_cfg={'model': 'datastore-model'})
        with patch.dict('os.environ', {'LLM_MODEL': 'ollama/llama3.2', 'LLM_API_KEY': '', 'LLM_API_BASE': ''}):
            result = get_llm_config(ds)
        assert result['model'] == 'ollama/llama3.2'

    def test_env_var_api_key_and_base_included(self):
        """LLM_API_KEY and LLM_API_BASE are picked up alongside LLM_MODEL."""
        from changedetectionio.llm.evaluator import get_llm_config
        ds = _make_datastore()
        env = {'LLM_MODEL': 'gpt-4o', 'LLM_API_KEY': 'env-key', 'LLM_API_BASE': 'http://localhost:11434'}
        with patch.dict('os.environ', env):
            result = get_llm_config(ds)
        assert result['api_key'] == 'env-key'
        assert result['api_base'] == 'http://localhost:11434'

    def test_llm_configured_via_env_true_when_model_set(self):
        """llm_configured_via_env() returns True when LLM_MODEL is set."""
        from changedetectionio.llm.evaluator import llm_configured_via_env
        with patch.dict('os.environ', {'LLM_MODEL': 'gpt-4o-mini'}):
            assert llm_configured_via_env() is True

    def test_llm_configured_via_env_false_when_not_set(self):
        """llm_configured_via_env() returns False when LLM_MODEL is absent."""
        from changedetectionio.llm.evaluator import llm_configured_via_env
        env = {k: '' for k in ['LLM_MODEL', 'LLM_API_KEY', 'LLM_API_BASE']}
        with patch.dict('os.environ', env, clear=False):
            # Ensure LLM_MODEL is truly absent
            import os
            os.environ.pop('LLM_MODEL', None)
            assert llm_configured_via_env() is False


# ---------------------------------------------------------------------------
# evaluate_change
# ---------------------------------------------------------------------------

class TestEvaluateChange:
    def test_returns_none_when_llm_not_configured(self):
        from changedetectionio.llm.evaluator import evaluate_change
        ds = _make_datastore(llm_cfg={})  # no model
        watch = _make_watch(llm_intent='flag price drops')
        result = evaluate_change(watch, ds, diff='- $500\n+ $400')
        assert result is None

    def test_returns_none_when_no_intent(self):
        from changedetectionio.llm.evaluator import evaluate_change
        ds = _make_datastore(llm_cfg={'model': 'gpt-4o-mini'})
        watch = _make_watch(llm_intent='')
        result = evaluate_change(watch, ds, diff='some diff')
        assert result is None

    def test_returns_not_important_for_empty_diff(self):
        from changedetectionio.llm.evaluator import evaluate_change
        ds = _make_datastore(llm_cfg={'model': 'gpt-4o-mini'})
        watch = _make_watch(llm_intent='flag price drops')
        result = evaluate_change(watch, ds, diff='')
        assert result == {'important': False, 'summary': ''}

    def test_returns_not_important_for_whitespace_diff(self):
        from changedetectionio.llm.evaluator import evaluate_change
        ds = _make_datastore(llm_cfg={'model': 'gpt-4o-mini'})
        watch = _make_watch(llm_intent='flag price drops')
        result = evaluate_change(watch, ds, diff='   \n  ')
        assert result == {'important': False, 'summary': ''}

    def test_calls_llm_and_returns_result(self):
        from changedetectionio.llm.evaluator import evaluate_change

        ds = _make_datastore(llm_cfg={'model': 'gpt-4o-mini', 'api_key': 'sk-test'})
        watch = _make_watch(llm_intent='flag price drops')

        llm_response = '{"important": true, "summary": "Price dropped from $500 to $400"}'
        with patch('changedetectionio.llm.client.completion', return_value=(llm_response, 150)):
            result = evaluate_change(watch, ds, diff='- $500\n+ $400')

        assert result['important'] is True
        assert 'Price dropped' in result['summary']

    def test_cache_hit_skips_llm_call(self):
        from changedetectionio.llm.evaluator import evaluate_change
        import hashlib

        ds = _make_datastore(llm_cfg={'model': 'gpt-4o-mini', 'api_key': 'sk-test'})
        watch = _make_watch(llm_intent='flag price drops')

        diff = '- $500\n+ $400'
        intent = 'flag price drops'
        cache_key = hashlib.sha256(f"{intent}||{diff}".encode()).hexdigest()
        watch['llm_evaluation_cache'] = {
            cache_key: {'important': True, 'summary': 'cached result'}
        }

        with patch('changedetectionio.llm.client.completion') as mock_llm:
            result = evaluate_change(watch, ds, diff=diff)
            mock_llm.assert_not_called()

        assert result['summary'] == 'cached result'

    def test_llm_failure_returns_important_true(self):
        """On LLM error, notification should NOT be suppressed (fail open)."""
        from changedetectionio.llm.evaluator import evaluate_change

        ds = _make_datastore(llm_cfg={'model': 'gpt-4o-mini', 'api_key': 'sk-test'})
        watch = _make_watch(llm_intent='flag price drops')

        with patch('changedetectionio.llm.client.completion', side_effect=Exception('API timeout')):
            result = evaluate_change(watch, ds, diff='- $500\n+ $400')

        assert result['important'] is True
        assert result['summary'] == ''

    def test_unimportant_result_from_llm(self):
        from changedetectionio.llm.evaluator import evaluate_change

        ds = _make_datastore(llm_cfg={'model': 'gpt-4o-mini'})
        watch = _make_watch(llm_intent='only alert on price drops')

        llm_response = '{"important": false, "summary": "Only a footer copyright year changed"}'
        with patch('changedetectionio.llm.client.completion', return_value=(llm_response, 45)):
            result = evaluate_change(watch, ds, diff='- Copyright 2023\n+ Copyright 2024')

        assert result['important'] is False
        assert 'footer' in result['summary'].lower() or 'copyright' in result['summary'].lower()

    def test_last_tokens_used_stored_after_eval(self):
        """watch['llm_last_tokens_used'] is set to the token count after a successful call."""
        from changedetectionio.llm.evaluator import evaluate_change

        ds = _make_datastore(llm_cfg={'model': 'gpt-4o-mini'})
        watch = _make_watch(llm_intent='flag price drops')

        llm_response = '{"important": true, "summary": "Price fell"}'
        with patch('changedetectionio.llm.client.completion', return_value=(llm_response, 123)):
            evaluate_change(watch, ds, diff='- $500\n+ $300')

        assert watch.get('llm_last_tokens_used') == 123

    def test_cumulative_tokens_accumulate_across_evals(self):
        """Each eval adds its tokens to watch['llm_tokens_used_cumulative']."""
        from changedetectionio.llm.evaluator import evaluate_change

        ds = _make_datastore(llm_cfg={'model': 'gpt-4o-mini'})
        watch = _make_watch(llm_intent='flag price drops')

        resp1 = '{"important": true, "summary": "First"}'
        resp2 = '{"important": false, "summary": "Second"}'

        with patch('changedetectionio.llm.client.completion', return_value=(resp1, 80)):
            evaluate_change(watch, ds, diff='- $500\n+ $400')

        # Second call needs a different diff to avoid cache hit
        with patch('changedetectionio.llm.client.completion', return_value=(resp2, 60)):
            evaluate_change(watch, ds, diff='- $400\n+ $350')

        assert watch.get('llm_tokens_used_cumulative') == 140


# ---------------------------------------------------------------------------
# Token budget enforcement
# ---------------------------------------------------------------------------

class TestTokenBudget:
    def test_no_limits_always_returns_true(self):
        """When no limits configured, budget check always passes."""
        from changedetectionio.llm.evaluator import _check_token_budget

        watch = _make_watch()
        cfg = {}  # no limits

        assert _check_token_budget(watch, cfg, tokens_this_call=10_000) is True

    def test_per_check_limit_exceeded_returns_false(self):
        """Tokens on this call exceeding per-check limit → False."""
        from changedetectionio.llm.evaluator import _check_token_budget

        watch = _make_watch()
        cfg = {'max_tokens_per_check': 100}

        result = _check_token_budget(watch, cfg, tokens_this_call=150)
        assert result is False

    def test_per_check_limit_not_exceeded_returns_true(self):
        """Tokens on this call within per-check limit → True."""
        from changedetectionio.llm.evaluator import _check_token_budget

        watch = _make_watch()
        cfg = {'max_tokens_per_check': 200}

        result = _check_token_budget(watch, cfg, tokens_this_call=150)
        assert result is True

    def test_cumulative_limit_exceeded_returns_false(self):
        """Total accumulated tokens exceeding cumulative limit → False."""
        from changedetectionio.llm.evaluator import _check_token_budget

        watch = _make_watch()
        watch['llm_tokens_used_cumulative'] = 900
        cfg = {'max_tokens_cumulative': 1000}

        # This call adds 200 → total 1100 > 1000
        result = _check_token_budget(watch, cfg, tokens_this_call=200)
        assert result is False

    def test_cumulative_limit_not_yet_exceeded_returns_true(self):
        """Total accumulated tokens within cumulative limit → True."""
        from changedetectionio.llm.evaluator import _check_token_budget

        watch = _make_watch()
        watch['llm_tokens_used_cumulative'] = 500
        cfg = {'max_tokens_cumulative': 1000}

        result = _check_token_budget(watch, cfg, tokens_this_call=100)
        assert result is True

    def test_tokens_accumulated_into_watch(self):
        """tokens_this_call is added to watch['llm_tokens_used_cumulative']."""
        from changedetectionio.llm.evaluator import _check_token_budget

        watch = _make_watch()
        watch['llm_tokens_used_cumulative'] = 300
        cfg = {}

        _check_token_budget(watch, cfg, tokens_this_call=75)
        assert watch['llm_tokens_used_cumulative'] == 375

    def test_zero_tokens_call_does_not_change_cumulative(self):
        """Calling with tokens_this_call=0 (pre-flight check) doesn't modify cumulative."""
        from changedetectionio.llm.evaluator import _check_token_budget

        watch = _make_watch()
        watch['llm_tokens_used_cumulative'] = 200
        cfg = {}

        _check_token_budget(watch, cfg, tokens_this_call=0)
        assert watch['llm_tokens_used_cumulative'] == 200

    def test_evaluate_change_skips_call_when_cumulative_over_budget(self):
        """Pre-flight cumulative check: if already over budget, skip LLM call and fail open."""
        from changedetectionio.llm.evaluator import evaluate_change

        ds = _make_datastore(llm_cfg={'model': 'gpt-4o-mini', 'max_tokens_cumulative': 100})
        watch = _make_watch(llm_intent='flag price drops')
        watch['llm_tokens_used_cumulative'] = 500  # already far over

        with patch('changedetectionio.llm.client.completion') as mock_llm:
            result = evaluate_change(watch, ds, diff='- $500\n+ $400')
            mock_llm.assert_not_called()

        # Fail open: important=True so the notification is NOT suppressed
        assert result == {'important': True, 'summary': ''}

    def test_evaluate_change_per_check_limit_fails_open(self):
        """Per-check token exceeded after call → result still returned (fail open)."""
        from changedetectionio.llm.evaluator import evaluate_change

        # max_tokens_per_check is 50, but the call returns 150 tokens
        ds = _make_datastore(llm_cfg={'model': 'gpt-4o-mini', 'max_tokens_per_check': 50})
        watch = _make_watch(llm_intent='flag price drops')

        llm_response = '{"important": false, "summary": "Only minor change"}'
        with patch('changedetectionio.llm.client.completion', return_value=(llm_response, 150)):
            result = evaluate_change(watch, ds, diff='- $500\n+ $499')

        # LLM said not important, but even with per-check warning the result is returned
        # (budget warning is logged but evaluation result is still used)
        assert result is not None
        assert 'important' in result
