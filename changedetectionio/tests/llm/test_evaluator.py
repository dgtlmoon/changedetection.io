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


def _make_tag(ai=True, **fields):
    """Build a tag dict.

    `ai` is the group's single AI control (llm_backend_profile): True = on, and its AI
    settings apply to its watches; False = off for every watch in the group; None = the
    group has no say. Defaults to True because most cases here are about what a group set
    to "On" does.
    """
    tag = {'title': 'grp', 'llm_backend_profile': ai}
    tag.update(fields)
    return tag


def _make_watch(llm_intent='', llm_change_summary='', tags=None, uuid='test-uuid-1234'):
    w = {}
    w['llm_intent'] = llm_intent
    w['llm_change_summary'] = llm_change_summary
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

        tag = _make_tag(title='mygroup', llm_intent='group intent')
        ds = _make_datastore(tags={'tag-1': tag})
        watch = _make_watch(llm_intent='watch intent', tags=['tag-1'])

        intent, source = resolve_intent(watch, ds)
        assert intent == 'watch intent'
        assert source == 'watch'

    def test_tag_intent_used_when_watch_has_none(self):
        from changedetectionio.llm.evaluator import resolve_intent

        tag = _make_tag(title='pricing-group', llm_intent='flag price drops')
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
        """An opted-in tag's intent propagates to every watch in the tag."""
        from changedetectionio.llm.evaluator import resolve_intent

        tag = _make_tag(title='job-board', llm_intent='new engineering jobs')
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
# The group's AI setting gates the whole cascade
# ---------------------------------------------------------------------------

class TestGroupAiSettingGatesTheCascade:
    def test_only_the_on_state_hands_settings_down(self):
        from changedetectionio.llm.evaluator import tag_llm_applies_to_watches
        assert tag_llm_applies_to_watches(_make_tag(ai=True)) is True
        # "Off" suppresses AI rather than lending prompts; "leave it to each watch" and tags
        # predating the setting (and missing tags) hand nothing down either
        assert tag_llm_applies_to_watches(_make_tag(ai=False)) is False
        assert tag_llm_applies_to_watches(_make_tag(ai=None)) is False
        assert tag_llm_applies_to_watches({'title': 'legacy'}) is False
        assert tag_llm_applies_to_watches(None) is False

    def test_intent_not_inherited_when_group_is_off(self):
        from changedetectionio.llm.evaluator import resolve_intent
        tag = _make_tag(ai=False, title='pricing-group', llm_intent='flag price drops')
        ds = _make_datastore(tags={'tag-1': tag})
        watch = _make_watch(llm_intent='', tags=['tag-1'])
        assert resolve_intent(watch, ds) == ('', '')

    def test_field_not_inherited_when_group_is_off(self):
        from changedetectionio.llm.evaluator import resolve_llm_field
        tag = _make_tag(ai=False, llm_change_summary='list new events')
        ds = _make_datastore(tags={'t1': tag})
        watch = _make_watch(llm_change_summary='', tags=['t1'])
        assert resolve_llm_field(watch, ds, 'llm_change_summary') == ('', '')

    def test_summary_prompt_not_inherited_when_group_is_off(self):
        from changedetectionio.llm.evaluator import get_effective_summary_prompt
        tag = _make_tag(ai=False, llm_change_summary='TAG')
        ds = _make_datastore(llm_cfg={'change_summary_default': 'GLOBAL'}, tags={'t1': tag})
        watch = _make_watch(llm_change_summary='', tags=['t1'])
        assert get_effective_summary_prompt(watch, ds) == 'GLOBAL'

    def test_first_group_set_to_on_wins_over_an_earlier_one_that_is_off(self):
        """A group that isn't "On" is skipped entirely, not treated as "found, but empty"."""
        from changedetectionio.llm.evaluator import resolve_intent
        ds = _make_datastore(tags={
            'ignored': _make_tag(ai=False, title='ignored-group', llm_intent='IGNORED'),
            'used': _make_tag(ai=True, title='used-group', llm_intent='USED'),
        })
        watch = _make_watch(llm_intent='', tags=['ignored', 'used'])
        assert resolve_intent(watch, ds) == ('USED', 'used-group')


# ---------------------------------------------------------------------------
# llm_enabled_for_watch — per-watch / per-group AI on-off switch (#4204)
# ---------------------------------------------------------------------------

class TestLlmEnabledForWatch:
    def test_enabled_by_default(self):
        """Watches predating the switch (no key at all) keep AI on."""
        from changedetectionio.llm.evaluator import llm_enabled_for_watch
        ds = _make_datastore()
        assert llm_enabled_for_watch(_make_watch(), ds) == (True, 'watch')

    def test_watch_switch_off(self):
        from changedetectionio.llm.evaluator import llm_enabled_for_watch
        ds = _make_datastore()
        watch = _make_watch()
        watch['llm_backend_profile'] = False
        assert llm_enabled_for_watch(watch, ds) == (False, 'watch')

    def test_group_switch_overrides_watch_off(self):
        """"The group setting overrides any watch on/off" — group ON beats watch OFF."""
        from changedetectionio.llm.evaluator import llm_enabled_for_watch
        tag = _make_tag(ai=True, title='ai-group')
        ds = _make_datastore(tags={'t1': tag})
        watch = _make_watch(tags=['t1'])
        watch['llm_backend_profile'] = False
        assert llm_enabled_for_watch(watch, ds) == (True, 'ai-group')

    def test_group_switch_overrides_watch_on(self):
        from changedetectionio.llm.evaluator import llm_enabled_for_watch
        tag = _make_tag(ai=False, title='no-ai-group')
        ds = _make_datastore(tags={'t1': tag})
        watch = _make_watch(tags=['t1'])
        watch['llm_backend_profile'] = True
        assert llm_enabled_for_watch(watch, ds) == (False, 'no-ai-group')

    def test_group_leaving_it_to_each_watch_does_not_decide(self):
        from changedetectionio.llm.evaluator import llm_enabled_for_watch
        ds = _make_datastore(tags={'t1': _make_tag(ai=None, title='undecided-group')})
        watch = _make_watch(tags=['t1'])
        watch['llm_backend_profile'] = False
        assert llm_enabled_for_watch(watch, ds) == (False, 'watch')

    def test_group_without_the_key_leaves_it_to_the_watch(self):
        """Tags predating the setting behave like "leave it to each watch"."""
        from changedetectionio.llm.evaluator import llm_enabled_for_watch
        ds = _make_datastore(tags={'t1': {'title': 'legacy'}})
        watch = _make_watch(tags=['t1'])
        watch['llm_backend_profile'] = False
        assert llm_enabled_for_watch(watch, ds) == (False, 'watch')

    def test_first_deciding_group_wins(self):
        """An undecided group is skipped; the next group with an opinion decides."""
        from changedetectionio.llm.evaluator import llm_enabled_for_watch
        ds = _make_datastore(tags={
            'a': _make_tag(ai=None, title='undecided-group'),
            'b': _make_tag(ai=False, title='no-ai-group'),
        })
        watch = _make_watch(tags=['a', 'b'])
        assert llm_enabled_for_watch(watch, ds) == (False, 'no-ai-group')


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

    def test_returns_none_for_empty_diff(self):
        from changedetectionio.llm.evaluator import evaluate_change
        ds = _make_datastore(llm_cfg={'model': 'gpt-4o-mini'})
        watch = _make_watch(llm_intent='flag price drops')
        result = evaluate_change(watch, ds, diff='')
        assert result is None

    def test_returns_none_for_whitespace_diff(self):
        from changedetectionio.llm.evaluator import evaluate_change
        ds = _make_datastore(llm_cfg={'model': 'gpt-4o-mini'})
        watch = _make_watch(llm_intent='flag price drops')
        result = evaluate_change(watch, ds, diff='   \n  ')
        assert result is None

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

    def test_per_period_limit_exceeded_returns_false(self):
        """Per-period tokens exceeding the cap → False."""
        from changedetectionio.llm.evaluator import _check_token_budget, _get_month_key

        watch = _make_watch()
        watch['llm_tokens_this_period'] = 900
        watch['llm_tokens_period_key'] = _get_month_key()
        cfg = {'max_tokens_per_count_period': 1000}

        # This call adds 200 → total 1100 > 1000
        result = _check_token_budget(watch, cfg, tokens_this_call=200)
        assert result is False

    def test_per_period_limit_not_yet_exceeded_returns_true(self):
        """Per-period tokens within the cap → True."""
        from changedetectionio.llm.evaluator import _check_token_budget, _get_month_key

        watch = _make_watch()
        watch['llm_tokens_this_period'] = 500
        watch['llm_tokens_period_key'] = _get_month_key()
        cfg = {'max_tokens_per_count_period': 1000}

        result = _check_token_budget(watch, cfg, tokens_this_call=100)
        assert result is True

    def test_period_rollover_zeroes_counter(self):
        """Stale period_key triggers rollover: counter resets before this call's tokens are added."""
        from changedetectionio.llm.evaluator import _check_token_budget, _get_month_key

        watch = _make_watch()
        watch['llm_tokens_this_period'] = 999_999  # last period's giant total
        watch['llm_tokens_period_key'] = '1970-01'  # ancient — guaranteed stale
        cfg = {'max_tokens_per_count_period': 1000}

        # This call adds 100 → after rollover should be 100, under the 1000 cap
        result = _check_token_budget(watch, cfg, tokens_this_call=100)
        assert result is True
        assert watch['llm_tokens_this_period'] == 100
        assert watch['llm_tokens_period_key'] == _get_month_key()

    def test_tokens_accumulated_into_both_counters(self):
        """tokens_this_call increments both the lifetime stat and the per-period counter."""
        from changedetectionio.llm.evaluator import _check_token_budget, _get_month_key

        watch = _make_watch()
        watch['llm_tokens_used_cumulative'] = 300
        watch['llm_tokens_this_period'] = 50
        watch['llm_tokens_period_key'] = _get_month_key()
        cfg = {}

        _check_token_budget(watch, cfg, tokens_this_call=75)
        assert watch['llm_tokens_used_cumulative'] == 375
        assert watch['llm_tokens_this_period'] == 125

    def test_zero_tokens_call_does_not_change_counters(self):
        """Calling with tokens_this_call=0 (pre-flight check) doesn't modify counters."""
        from changedetectionio.llm.evaluator import _check_token_budget, _get_month_key

        watch = _make_watch()
        watch['llm_tokens_used_cumulative'] = 200
        watch['llm_tokens_this_period'] = 80
        watch['llm_tokens_period_key'] = _get_month_key()
        cfg = {}

        _check_token_budget(watch, cfg, tokens_this_call=0)
        assert watch['llm_tokens_used_cumulative'] == 200
        assert watch['llm_tokens_this_period'] == 80

    def test_evaluate_change_skips_call_when_per_period_over_budget(self):
        """Pre-flight check: if already over the period cap, skip the LLM call and fail open."""
        from changedetectionio.llm.evaluator import evaluate_change, _get_month_key

        ds = _make_datastore(llm_cfg={'model': 'gpt-4o-mini', 'max_tokens_per_count_period': 100})
        watch = _make_watch(llm_intent='flag price drops')
        watch['llm_tokens_this_period'] = 500  # already far over
        watch['llm_tokens_period_key'] = _get_month_key()

        with patch('changedetectionio.llm.client.completion') as mock_llm:
            result = evaluate_change(watch, ds, diff='- $500\n+ $400')
            mock_llm.assert_not_called()

        # Fail open: important=True so the notification is NOT suppressed
        assert result == {'important': True, 'summary': ''}


# ---------------------------------------------------------------------------
# resolve_llm_field (generic cascade)
# ---------------------------------------------------------------------------

class TestResolveLlmField:
    def test_watch_value_takes_priority(self):
        from changedetectionio.llm.evaluator import resolve_llm_field
        tag = _make_tag(title='mygroup', llm_change_summary='tag summary prompt')
        ds = _make_datastore(tags={'tag-1': tag})
        watch = _make_watch(llm_change_summary='watch summary prompt', tags=['tag-1'])
        value, source = resolve_llm_field(watch, ds, 'llm_change_summary')
        assert value == 'watch summary prompt'
        assert source == 'watch'

    def test_tag_value_used_when_watch_empty(self):
        from changedetectionio.llm.evaluator import resolve_llm_field
        tag = _make_tag(title='events-group', llm_change_summary='list new events')
        ds = _make_datastore(tags={'tag-1': tag})
        watch = _make_watch(llm_change_summary='', tags=['tag-1'])
        value, source = resolve_llm_field(watch, ds, 'llm_change_summary')
        assert value == 'list new events'
        assert source == 'events-group'

    def test_returns_empty_when_not_set_anywhere(self):
        from changedetectionio.llm.evaluator import resolve_llm_field
        ds = _make_datastore()
        watch = _make_watch()
        value, source = resolve_llm_field(watch, ds, 'llm_change_summary')
        assert value == ''
        assert source == ''

    def test_works_for_llm_intent_field_too(self):
        """resolve_llm_field is generic — works for llm_intent same as llm_change_summary."""
        from changedetectionio.llm.evaluator import resolve_llm_field
        tag = _make_tag(llm_intent='flag price drops')
        ds = _make_datastore(tags={'t1': tag})
        watch = _make_watch(llm_intent='', tags=['t1'])
        value, source = resolve_llm_field(watch, ds, 'llm_intent')
        assert value == 'flag price drops'


# ---------------------------------------------------------------------------
# summarise_change
# ---------------------------------------------------------------------------

class TestSummariseChange:
    def test_returns_empty_when_llm_not_configured(self):
        from changedetectionio.llm.evaluator import summarise_change
        ds = _make_datastore(llm_cfg={})
        watch = _make_watch(llm_change_summary='List what changed')
        result = summarise_change(watch, ds, diff='- old\n+ new')
        assert result == ''

    def test_uses_default_prompt_when_no_summary_prompt(self):
        """When llm_change_summary is empty, falls back to DEFAULT_CHANGE_SUMMARY_PROMPT."""
        from changedetectionio.llm.evaluator import summarise_change, DEFAULT_CHANGE_SUMMARY_PROMPT
        ds = _make_datastore(llm_cfg={'model': 'gpt-4o-mini', 'api_key': 'sk-test'})
        watch = _make_watch(llm_change_summary='')
        with patch('changedetectionio.llm.client.completion',
                   return_value=('A new item was added.', 40)) as mock_llm:
            result = summarise_change(watch, ds, diff='- old\n+ new')
        mock_llm.assert_called_once()
        # Default prompt must appear in the user message
        call_messages = mock_llm.call_args.kwargs['messages']
        user_msg = next(m['content'] for m in call_messages if m['role'] == 'user')
        assert DEFAULT_CHANGE_SUMMARY_PROMPT in user_msg
        assert result == 'A new item was added.'

    def test_returns_empty_when_diff_empty(self):
        from changedetectionio.llm.evaluator import summarise_change
        ds = _make_datastore(llm_cfg={'model': 'gpt-4o-mini'})
        watch = _make_watch(llm_change_summary='List what changed')
        with patch('changedetectionio.llm.client.completion') as mock_llm:
            result = summarise_change(watch, ds, diff='')
            mock_llm.assert_not_called()
        assert result == ''

    def test_calls_llm_and_returns_plain_text(self):
        from changedetectionio.llm.evaluator import summarise_change
        ds = _make_datastore(llm_cfg={'model': 'gpt-4o-mini', 'api_key': 'sk-test'})
        watch = _make_watch(llm_change_summary='List new events in English')
        with patch('changedetectionio.llm.client.completion',
                   return_value=('3 new events added: Jazz Night, Art Show, Comedy Gig', 80)):
            result = summarise_change(watch, ds, diff='+ Jazz Night\n+ Art Show\n+ Comedy Gig')
        assert 'Jazz Night' in result
        assert 'Art Show' in result

    def test_cascades_from_tag(self):
        """llm_change_summary on a tag propagates to watches in that tag."""
        from changedetectionio.llm.evaluator import summarise_change
        tag = _make_tag(title='events', llm_change_summary='Translate events to English')
        ds = _make_datastore(llm_cfg={'model': 'gpt-4o-mini'}, tags={'tag-1': tag})
        watch = _make_watch(llm_change_summary='', tags=['tag-1'])
        with patch('changedetectionio.llm.client.completion',
                   return_value=('New concert added on Friday', 60)):
            result = summarise_change(watch, ds, diff='+ Konzert am Freitag')
        assert result == 'New concert added on Friday'

    def test_llm_failure_raises(self):
        """On LLM error, summarise_change re-raises so callers can surface the error."""
        from changedetectionio.llm.evaluator import summarise_change
        ds = _make_datastore(llm_cfg={'model': 'gpt-4o-mini'})
        watch = _make_watch(llm_change_summary='Describe the change')
        with patch('changedetectionio.llm.client.completion', side_effect=Exception('timeout')):
            with pytest.raises(Exception, match='timeout'):
                summarise_change(watch, ds, diff='- old\n+ new')

    def test_uses_higher_token_limit_than_eval(self):
        """summarise_change passes a dynamic max_tokens larger than the eval default (200)."""
        from changedetectionio.llm.evaluator import summarise_change, _summary_max_tokens
        ds = _make_datastore(llm_cfg={'model': 'gpt-4o-mini'})
        watch = _make_watch(llm_change_summary='Describe changes')
        diff = '- old\n+ new'
        with patch('changedetectionio.llm.client.completion',
                   return_value=('Some summary', 100)) as mock_llm:
            summarise_change(watch, ds, diff=diff)
        call_kwargs = mock_llm.call_args
        passed_max_tokens = call_kwargs.kwargs.get('max_tokens')
        assert passed_max_tokens == _summary_max_tokens(diff)
        assert passed_max_tokens >= 400  # always more generous than eval cap of 200

    def test_dynamic_token_cap_scales_with_diff_size(self):
        """Larger diffs produce a higher max_tokens cap, bounded at 3000."""
        from changedetectionio.llm.evaluator import _summary_max_tokens
        assert _summary_max_tokens('x' * 100)   == 400   # floor
        assert _summary_max_tokens('x' * 4000)  == 1000
        assert _summary_max_tokens('x' * 12000) == 3000  # ceiling
        assert _summary_max_tokens('x' * 99999) == 3000  # never exceeds ceiling


# ---------------------------------------------------------------------------
# compute_summary_cache_key / get_effective_summary_prompt
# ---------------------------------------------------------------------------

class TestSummaryCacheKey:
    def test_same_inputs_produce_same_key(self):
        from changedetectionio.llm.evaluator import compute_summary_cache_key
        key1 = compute_summary_cache_key('+ new line', 'describe changes')
        key2 = compute_summary_cache_key('+ new line', 'describe changes')
        assert key1 == key2

    def test_different_diff_produces_different_key(self):
        from changedetectionio.llm.evaluator import compute_summary_cache_key
        key1 = compute_summary_cache_key('+ line A', 'prompt')
        key2 = compute_summary_cache_key('+ line B', 'prompt')
        assert key1 != key2

    def test_different_prompt_produces_different_key(self):
        from changedetectionio.llm.evaluator import compute_summary_cache_key
        key1 = compute_summary_cache_key('diff', 'list changes')
        key2 = compute_summary_cache_key('diff', 'translate to English')
        assert key1 != key2

    def test_key_is_16_hex_chars(self):
        from changedetectionio.llm.evaluator import compute_summary_cache_key
        key = compute_summary_cache_key('diff', 'prompt')
        assert len(key) == 16
        assert all(c in '0123456789abcdef' for c in key)

    def test_get_effective_prompt_returns_custom_when_set(self):
        from changedetectionio.llm.evaluator import get_effective_summary_prompt
        ds = _make_datastore()
        watch = _make_watch(llm_change_summary='My custom prompt')
        assert get_effective_summary_prompt(watch, ds) == 'My custom prompt'

    def test_get_effective_prompt_returns_default_when_empty(self):
        from changedetectionio.llm.evaluator import get_effective_summary_prompt, DEFAULT_CHANGE_SUMMARY_PROMPT
        ds = _make_datastore()
        watch = _make_watch(llm_change_summary='')
        assert get_effective_summary_prompt(watch, ds) == DEFAULT_CHANGE_SUMMARY_PROMPT

    def test_get_effective_prompt_cascades_from_tag(self):
        from changedetectionio.llm.evaluator import get_effective_summary_prompt
        tag = _make_tag(llm_change_summary='tag-level prompt')
        ds = _make_datastore(tags={'t1': tag})
        watch = _make_watch(llm_change_summary='', tags=['t1'])
        assert get_effective_summary_prompt(watch, ds) == 'tag-level prompt'


# ---------------------------------------------------------------------------
# llm_change_summary_mode — append vs replace (#4251)
# ---------------------------------------------------------------------------

class TestSummaryPromptAppendMode:
    """A watch/tag may add to the prompt it inherits instead of holding a private copy.

    Everything here must leave the legacy 'replace' path byte-identical — that is what
    the TestSummaryCacheKey cases above pin.
    """

    def test_global_default_used_as_base_when_nothing_else_set(self):
        from changedetectionio.llm.evaluator import get_effective_summary_prompt
        ds = _make_datastore(llm_cfg={'change_summary_default': 'GLOBAL'})
        assert get_effective_summary_prompt(_make_watch(), ds) == 'GLOBAL'

    def test_watch_appends_to_global_default(self):
        from changedetectionio.llm.evaluator import get_effective_summary_prompt
        ds = _make_datastore(llm_cfg={'change_summary_default': 'GLOBAL'})
        watch = _make_watch(llm_change_summary='Also mention the SKU.')
        watch['llm_change_summary_mode'] = 'append'
        assert get_effective_summary_prompt(watch, ds) == 'GLOBAL\n\nAlso mention the SKU.'

    def test_watch_appends_to_hardcoded_default_when_no_global_set(self):
        from changedetectionio.llm.evaluator import get_effective_summary_prompt, DEFAULT_CHANGE_SUMMARY_PROMPT
        ds = _make_datastore()
        watch = _make_watch(llm_change_summary='Also mention the SKU.')
        watch['llm_change_summary_mode'] = 'append'
        result = get_effective_summary_prompt(watch, ds)
        assert result == f'{DEFAULT_CHANGE_SUMMARY_PROMPT}\n\nAlso mention the SKU.'

    def test_watch_append_targets_the_tag_prompt_when_a_tag_supplies_one(self):
        """The watch appends to what it would otherwise have inherited — here the tag."""
        from changedetectionio.llm.evaluator import get_effective_summary_prompt
        tag = _make_tag(llm_change_summary='TAG')
        ds = _make_datastore(llm_cfg={'change_summary_default': 'GLOBAL'}, tags={'t1': tag})
        watch = _make_watch(llm_change_summary='WATCH', tags=['t1'])
        watch['llm_change_summary_mode'] = 'append'
        assert get_effective_summary_prompt(watch, ds) == 'TAG\n\nWATCH'

    def test_tag_and_watch_can_both_append_forming_a_chain(self):
        from changedetectionio.llm.evaluator import get_effective_summary_prompt
        tag = _make_tag(llm_change_summary='TAG', llm_change_summary_mode='append')
        ds = _make_datastore(llm_cfg={'change_summary_default': 'GLOBAL'}, tags={'t1': tag})
        watch = _make_watch(llm_change_summary='WATCH', tags=['t1'])
        watch['llm_change_summary_mode'] = 'append'
        assert get_effective_summary_prompt(watch, ds) == 'GLOBAL\n\nTAG\n\nWATCH'

    def test_tag_appends_while_watch_replaces(self):
        from changedetectionio.llm.evaluator import get_effective_summary_prompt
        tag = _make_tag(llm_change_summary='TAG', llm_change_summary_mode='append')
        ds = _make_datastore(llm_cfg={'change_summary_default': 'GLOBAL'}, tags={'t1': tag})
        watch = _make_watch(llm_change_summary='WATCH', tags=['t1'])
        assert get_effective_summary_prompt(watch, ds) == 'WATCH'

    def test_append_mode_with_empty_text_changes_nothing(self):
        from changedetectionio.llm.evaluator import get_effective_summary_prompt
        ds = _make_datastore(llm_cfg={'change_summary_default': 'GLOBAL'})
        watch = _make_watch(llm_change_summary='')
        watch['llm_change_summary_mode'] = 'append'
        assert get_effective_summary_prompt(watch, ds) == 'GLOBAL'

    def test_missing_mode_key_behaves_as_replace(self):
        """Watches stored before this feature have no mode key at all."""
        from changedetectionio.llm.evaluator import get_effective_summary_prompt
        ds = _make_datastore(llm_cfg={'change_summary_default': 'GLOBAL'})
        watch = _make_watch(llm_change_summary='WATCH')
        assert 'llm_change_summary_mode' not in watch
        assert get_effective_summary_prompt(watch, ds) == 'WATCH'

    def test_append_changes_the_cache_key(self):
        """Toggling the mode must invalidate cached summaries, not silently reuse them."""
        from changedetectionio.llm.evaluator import get_effective_summary_prompt, compute_summary_cache_key
        ds = _make_datastore(llm_cfg={'change_summary_default': 'GLOBAL'})

        replacing = _make_watch(llm_change_summary='WATCH')
        appending = _make_watch(llm_change_summary='WATCH')
        appending['llm_change_summary_mode'] = 'append'

        key_replace = compute_summary_cache_key('diff', get_effective_summary_prompt(replacing, ds))
        key_append = compute_summary_cache_key('diff', get_effective_summary_prompt(appending, ds))
        assert key_replace != key_append
