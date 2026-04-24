"""
Unit tests for changedetectionio/llm/prompt_builder.py

All functions are pure — no external dependencies needed.
"""
import pytest
from changedetectionio.llm.prompt_builder import (
    build_eval_prompt,
    build_eval_system_prompt,
    build_setup_prompt,
    build_setup_system_prompt,
    SNAPSHOT_CONTEXT_CHARS,
)


class TestBuildEvalPrompt:
    def test_contains_intent(self):
        prompt = build_eval_prompt(intent='Alert on price drops', diff='- $500\n+ $400')
        assert 'Alert on price drops' in prompt

    def test_contains_diff(self):
        prompt = build_eval_prompt(intent='price', diff='- $500\n+ $400')
        assert '- $500' in prompt
        assert '+ $400' in prompt

    def test_optional_url_included_when_provided(self):
        prompt = build_eval_prompt(
            intent='price',
            diff='some diff',
            url='https://example.com/product',
        )
        assert 'https://example.com/product' in prompt

    def test_url_absent_when_not_provided(self):
        prompt = build_eval_prompt(intent='price', diff='diff')
        assert 'URL:' not in prompt

    def test_optional_title_included_when_provided(self):
        prompt = build_eval_prompt(
            intent='price',
            diff='diff',
            title='Example Product Page',
        )
        assert 'Example Product Page' in prompt

    def test_snapshot_context_included(self):
        snapshot = 'Current price: $400. Stock: in stock. Description: widget.'
        prompt = build_eval_prompt(
            intent='price',
            diff='- $500\n+ $400',
            current_snapshot=snapshot,
        )
        # Snapshot excerpt should appear somewhere in the prompt
        assert 'Current price' in prompt or '$400' in prompt

    def test_large_snapshot_trimmed_to_budget(self):
        # Snapshot larger than SNAPSHOT_CONTEXT_CHARS should be trimmed
        large_snapshot = 'irrelevant content line\n' * 2000
        prompt = build_eval_prompt(
            intent='price drop',
            diff='changed',
            current_snapshot=large_snapshot,
        )
        # Prompt should not be astronomically large
        assert len(prompt) < len(large_snapshot)

    def test_empty_snapshot_skipped(self):
        prompt_with = build_eval_prompt(intent='x', diff='d', current_snapshot='some text')
        prompt_without = build_eval_prompt(intent='x', diff='d', current_snapshot='')
        # Without snapshot should be shorter
        assert len(prompt_without) < len(prompt_with)


class TestBuildEvalSystemPrompt:
    def test_returns_string(self):
        result = build_eval_system_prompt()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_instructs_json_only_output(self):
        result = build_eval_system_prompt()
        assert 'JSON' in result or 'json' in result.lower()

    def test_defines_important_field(self):
        result = build_eval_system_prompt()
        assert 'important' in result

    def test_defines_summary_field(self):
        result = build_eval_system_prompt()
        assert 'summary' in result


class TestBuildSetupPrompt:
    def test_contains_intent(self):
        prompt = build_setup_prompt(
            intent='monitor footer changes',
            snapshot_text='<footer>Copyright 2024</footer>',
        )
        assert 'monitor footer changes' in prompt

    def test_contains_url_when_provided(self):
        prompt = build_setup_prompt(
            intent='price',
            snapshot_text='price: $10',
            url='https://shop.example.com',
        )
        assert 'https://shop.example.com' in prompt

    def test_url_absent_when_not_provided(self):
        prompt = build_setup_prompt(intent='price', snapshot_text='text')
        assert 'URL:' not in prompt

    def test_large_snapshot_trimmed(self):
        big_snapshot = 'unrelated junk line\n' * 500
        prompt = build_setup_prompt(
            intent='monitor price section',
            snapshot_text=big_snapshot,
        )
        assert len(prompt) < len(big_snapshot)


class TestBuildSetupSystemPrompt:
    def test_returns_string(self):
        result = build_setup_system_prompt()
        assert isinstance(result, str)

    def test_forbids_positional_selectors(self):
        result = build_setup_system_prompt()
        assert 'nth-child' in result or 'positional' in result

    def test_defines_needs_prefilter_field(self):
        result = build_setup_system_prompt()
        assert 'needs_prefilter' in result

    def test_defines_selector_field(self):
        result = build_setup_system_prompt()
        assert 'selector' in result
