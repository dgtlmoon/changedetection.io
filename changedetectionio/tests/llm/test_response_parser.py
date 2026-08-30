"""
Unit tests for changedetectionio/llm/response_parser.py

All functions are pure — no external dependencies needed.
"""

from changedetectionio.llm.response_parser import (
    _extract_json,
    parse_eval_response,
    parse_preview_response,
    parse_setup_response,
)


class TestExtractJson:
    def test_plain_json_passes_through(self):
        raw = '{"important": true, "summary": "price dropped"}'
        assert _extract_json(raw) == raw

    def test_strips_json_code_fence(self):
        raw = '```json\n{"important": false, "summary": "no match"}\n```'
        result = _extract_json(raw)
        assert result.startswith('{')
        assert '"important"' in result

    def test_strips_plain_code_fence(self):
        raw = '```\n{"important": true, "summary": "ok"}\n```'
        result = _extract_json(raw)
        assert result.startswith('{')

    def test_extracts_json_from_surrounding_text(self):
        raw = 'Here is my response: {"important": true, "summary": "match"} — done.'
        result = _extract_json(raw)
        assert result == '{"important": true, "summary": "match"}'

    def test_multiline_json(self):
        raw = '{\n  "important": false,\n  "summary": "nothing relevant"\n}'
        result = _extract_json(raw)
        assert '"important"' in result

    def test_strips_reasoning_think_tags(self):
        raw = (
            '<think>\n'
            'Let us consider if {"important": false} is right. Actually, yes.\n'
            '</think>\n'
            '{"important": true, "summary": "Price fell to $300"}'
        )
        result = _extract_json(raw)
        assert result == '{"important": true, "summary": "Price fell to $300"}'

    def test_strips_reasoning_think_tags_with_code_fence(self):
        raw = (
            '<think>\nThinking about the price change.\n</think>\n'
            '```json\n{"important": false, "summary": "Cosmetic change only"}\n```'
        )
        result = _extract_json(raw)
        assert '"important"' in result
        assert '<think>' not in result


class TestParseEvalResponse:
    def test_valid_important_true(self):
        raw = '{"important": true, "summary": "Price dropped from $500 to $400"}'
        result = parse_eval_response(raw)
        assert result['important'] is True
        assert result['summary'] == 'Price dropped from $500 to $400'

    def test_valid_important_false(self):
        raw = '{"important": false, "summary": "Only a date counter changed"}'
        result = parse_eval_response(raw)
        assert result['important'] is False
        assert 'date counter' in result['summary']

    def test_string_false_evaluates_to_false(self):
        raw = '{"important": "false", "summary": "No relevant changes found"}'
        result = parse_eval_response(raw)
        assert result['important'] is False
        assert result['summary'] == 'No relevant changes found'

    def test_string_true_evaluates_to_true(self):
        raw = '{"important": "true", "summary": "Price updated"}'
        result = parse_eval_response(raw)
        assert result['important'] is True
        assert result['summary'] == 'Price updated'

    def test_markdown_fenced_response(self):
        raw = '```json\n{"important": true, "summary": "New job posted"}\n```'
        result = parse_eval_response(raw)
        assert result['important'] is True
        assert result['summary'] == 'New job posted'

    def test_reasoning_model_response_parsed_correctly(self):
        raw = (
            '<think>\n'
            '1. Checking diff: {"important": false} was our initial thought.\n'
            '2. However the price dropped from $100 to $80.\n'
            '</think>\n'
            '{"important": true, "summary": "Price dropped by $20"}'
        )
        result = parse_eval_response(raw)
        assert result['important'] is True
        assert result['summary'] == 'Price dropped by $20'

    def test_malformed_json_falls_back_to_safe_default(self):
        result = parse_eval_response('this is not json at all')
        assert result['important'] is False
        assert result['summary'] == ''

    def test_empty_string_falls_back(self):
        result = parse_eval_response('')
        assert result['important'] is False

    def test_truthy_integer_coerced_to_bool(self):
        raw = '{"important": 1, "summary": "yes"}'
        result = parse_eval_response(raw)
        assert result['important'] is True

    def test_falsy_integer_coerced_to_bool(self):
        raw = '{"important": 0, "summary": "no"}'
        result = parse_eval_response(raw)
        assert result['important'] is False

    def test_summary_stripped_of_whitespace(self):
        raw = '{"important": false, "summary": "  no match  "}'
        result = parse_eval_response(raw)
        assert result['summary'] == 'no match'

    def test_missing_summary_defaults_to_empty_string(self):
        raw = '{"important": true}'
        result = parse_eval_response(raw)
        assert result['summary'] == ''

    def test_extra_keys_ignored(self):
        raw = '{"important": false, "summary": "skip", "confidence": 0.3, "debug": "xyz"}'
        result = parse_eval_response(raw)
        assert result['important'] is False
        assert result['summary'] == 'skip'


class TestParsePreviewResponse:
    def test_valid_found_true(self):
        raw = '{"found": true, "answer": "Price is $49.99"}'
        result = parse_preview_response(raw)
        assert result['found'] is True
        assert result['answer'] == 'Price is $49.99'

    def test_valid_found_false(self):
        raw = '{"found": false, "answer": "Item not listed"}'
        result = parse_preview_response(raw)
        assert result['found'] is False
        assert result['answer'] == 'Item not listed'

    def test_string_false_in_preview(self):
        raw = '{"found": "false", "answer": "Not found"}'
        result = parse_preview_response(raw)
        assert result['found'] is False
        assert result['answer'] == 'Not found'

    def test_preview_with_think_tags(self):
        raw = '<think>Looking for price...</think>\n{"found": true, "answer": "$19.99"}'
        result = parse_preview_response(raw)
        assert result['found'] is True
        assert result['answer'] == '$19.99'


class TestParseSetupResponse:
    def test_no_prefilter_needed(self):
        raw = '{"needs_prefilter": false, "selector": null, "reason": "intent is global"}'
        result = parse_setup_response(raw)
        assert result['needs_prefilter'] is False
        assert result['selector'] is None

    def test_string_false_in_setup(self):
        raw = '{"needs_prefilter": "false", "selector": null, "reason": "global"}'
        result = parse_setup_response(raw)
        assert result['needs_prefilter'] is False

    def test_semantic_selector_accepted(self):
        raw = (
            '{"needs_prefilter": true, "selector": "footer", "reason": "intent references footer"}'
        )
        result = parse_setup_response(raw)
        assert result['needs_prefilter'] is True
        assert result['selector'] == 'footer'

    def test_attribute_selector_accepted(self):
        raw = '{"needs_prefilter": true, "selector": "[class*=\'price\']", "reason": "pricing section"}'
        result = parse_setup_response(raw)
        assert result['needs_prefilter'] is True
        assert result['selector'] is not None

    def test_nth_child_positional_selector_rejected(self):
        raw = '{"needs_prefilter": true, "selector": "div:nth-child(3)", "reason": "third div"}'
        result = parse_setup_response(raw)
        assert result['selector'] is None
        assert result['needs_prefilter'] is False

    def test_nth_of_type_positional_selector_rejected(self):
        raw = '{"needs_prefilter": true, "selector": "p:nth-of-type(2)", "reason": "second p"}'
        result = parse_setup_response(raw)
        assert result['selector'] is None
        assert result['needs_prefilter'] is False

    def test_eq_positional_selector_rejected(self):
        raw = '{"needs_prefilter": true, "selector": "div:eq(0)", "reason": "first div"}'
        result = parse_setup_response(raw)
        assert result['selector'] is None

    def test_xpath_positional_selector_rejected(self):
        raw = '{"needs_prefilter": true, "selector": "//*[2]", "reason": "second element"}'
        result = parse_setup_response(raw)
        assert result['selector'] is None

    def test_selector_forced_to_null_when_needs_prefilter_false(self):
        # Even if selector is provided alongside needs_prefilter=false, selector is nulled
        raw = '{"needs_prefilter": false, "selector": "main", "reason": "not needed"}'
        result = parse_setup_response(raw)
        assert result['selector'] is None

    def test_malformed_json_safe_defaults(self):
        result = parse_setup_response('garbage text')
        assert result['needs_prefilter'] is False
        assert result['selector'] is None
        assert result['reason'] == ''

    def test_empty_response_safe_defaults(self):
        result = parse_setup_response('')
        assert result['needs_prefilter'] is False
