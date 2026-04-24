"""
Unit tests for changedetectionio/llm/response_parser.py

All functions are pure — no external dependencies needed.
"""
import pytest
from changedetectionio.llm.response_parser import (
    _extract_json,
    parse_eval_response,
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

    def test_markdown_fenced_response(self):
        raw = '```json\n{"important": true, "summary": "New job posted"}\n```'
        result = parse_eval_response(raw)
        assert result['important'] is True
        assert result['summary'] == 'New job posted'

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


class TestParseSetupResponse:
    def test_no_prefilter_needed(self):
        raw = '{"needs_prefilter": false, "selector": null, "reason": "intent is global"}'
        result = parse_setup_response(raw)
        assert result['needs_prefilter'] is False
        assert result['selector'] is None

    def test_semantic_selector_accepted(self):
        raw = '{"needs_prefilter": true, "selector": "footer", "reason": "intent references footer"}'
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
