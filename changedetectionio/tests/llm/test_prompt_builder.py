"""
Unit tests for changedetectionio/llm/prompt_builder.py

All functions are pure — no external dependencies needed.
"""
import pytest
from changedetectionio.llm.prompt_builder import (
    build_eval_prompt,
    build_eval_system_prompt,
    build_change_summary_prompt,
    build_preview_prompt,
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


class TestMetadataEnrichmentInPrompts:
    """The verbatim structured-metadata block must land in the eval/summary/preview
    user prompts when provided, and leave them unchanged when absent."""

    METADATA = (
        "Page context: site: ExampleShop | og:type: product\n"
        "Structured metadata found on the page (JSON-LD):\n"
        '{"@type":"Product","name":"Acme Widget","sku":"12345","color":"blue"}'
    )

    def test_eval_prompt_includes_metadata(self):
        prompt = build_eval_prompt(intent='alert on SKU change', diff='- a\n+ b',
                                   metadata=self.METADATA)
        assert self.METADATA in prompt
        # A field we never whitelisted must survive verbatim
        assert '"sku":"12345"' in prompt
        assert '"color":"blue"' in prompt
        # The block is appended AFTER the diff (diff stays the freshest pre-metadata content)
        assert prompt.index('What changed (diff):') < prompt.index('Structured metadata found')

    def test_eval_prompt_unchanged_without_metadata(self):
        with_meta = build_eval_prompt(intent='i', diff='d', metadata=self.METADATA)
        without = build_eval_prompt(intent='i', diff='d')
        assert 'Structured metadata found' not in without
        assert len(without) < len(with_meta)

    def test_summary_prompt_includes_metadata(self):
        prompt = build_change_summary_prompt(diff='- a\n+ b', custom_prompt='list the SKUs',
                                             metadata=self.METADATA)
        assert self.METADATA in prompt
        assert '"sku":"12345"' in prompt

    def test_summary_prompt_unchanged_without_metadata(self):
        without = build_change_summary_prompt(diff='- a\n+ b', custom_prompt='x')
        assert 'Structured metadata found' not in without

    def test_preview_prompt_includes_metadata(self):
        prompt = build_preview_prompt(intent='what is the SKU?', content='some page text',
                                      metadata=self.METADATA)
        assert self.METADATA in prompt
        assert '"sku":"12345"' in prompt

    def test_preview_prompt_unchanged_without_metadata(self):
        without = build_preview_prompt(intent='q', content='page text')
        assert 'Structured metadata found' not in without

    def test_empty_metadata_appends_nothing(self):
        # Falsy metadata ('') must not add a trailing block/whitespace section
        assert build_eval_prompt(intent='i', diff='d', metadata='') == build_eval_prompt(intent='i', diff='d')
        assert (build_change_summary_prompt(diff='d', custom_prompt='c', metadata='')
                == build_change_summary_prompt(diff='d', custom_prompt='c'))
        assert (build_preview_prompt(intent='i', content='c', metadata='')
                == build_preview_prompt(intent='i', content='c'))


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
