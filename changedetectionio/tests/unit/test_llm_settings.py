#!/usr/bin/env python3

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_llm_settings

import unittest

from pydantic import ValidationError

from changedetectionio.model.LLMSettings import (
    LLMSettings,
    LLM_DEFAULT_BUDGET_ACTION,
    LLM_DEFAULT_LOCAL_TOKEN_MULTIPLIER,
    LLM_DEFAULT_MAX_INPUT_CHARS,
    LLM_DEFAULT_MAX_SUMMARY_TOKENS,
    LLM_DEFAULT_THINKING_BUDGET,
)


class TestLLMSettingsDefaults(unittest.TestCase):
    def test_empty_dict_yields_default_model(self):
        s = LLMSettings.model_validate({})
        self.assertTrue(s.enabled)
        self.assertFalse(s.debug)
        self.assertEqual(s.model, '')
        self.assertEqual(s.api_key, '')
        self.assertEqual(s.thinking_budget, LLM_DEFAULT_THINKING_BUDGET)
        self.assertEqual(s.max_summary_tokens, LLM_DEFAULT_MAX_SUMMARY_TOKENS)
        self.assertEqual(s.local_token_multiplier, LLM_DEFAULT_LOCAL_TOKEN_MULTIPLIER)
        self.assertEqual(s.max_input_chars, LLM_DEFAULT_MAX_INPUT_CHARS)
        self.assertEqual(s.budget_action, LLM_DEFAULT_BUDGET_ACTION)
        self.assertEqual(s.tokens_total_cumulative, 0)
        self.assertEqual(s.cost_usd_this_month, 0.0)

    def test_default_construct_matches_validate_empty(self):
        self.assertEqual(LLMSettings().model_dump(), LLMSettings.model_validate({}).model_dump())


class TestLLMSettingsAliases(unittest.TestCase):
    def test_stripped_storage_keys_validate(self):
        s = LLMSettings.model_validate({'model': 'gpt-4o-mini', 'enabled': False})
        self.assertEqual(s.model, 'gpt-4o-mini')
        self.assertFalse(s.enabled)

    def test_aliased_form_keys_validate(self):
        s = LLMSettings.model_validate({'llm_model': 'claude-3-5-haiku-20251001', 'llm_enabled': False})
        self.assertEqual(s.model, 'claude-3-5-haiku-20251001')
        self.assertFalse(s.enabled)

    def test_both_field_name_and_alias_in_same_dict_rejected(self):
        # extra='forbid' makes the dict shape exclusive: a given field can be
        # set via field name OR alias, but not both. This is why the settings
        # POST handler dumps the existing model with by_alias=True before
        # merging form input — keeps both sides on the alias shape so there's
        # no duplicate key.
        with self.assertRaises(ValidationError):
            LLMSettings.model_validate({'model': 'A', 'llm_model': 'B'})

    def test_dump_by_alias_then_merge_form_lets_form_value_win(self):
        # The POST-handler merge pattern: dump existing as aliases so it lines
        # up with form input (also aliases). Without by_alias=True we'd have
        # mixed field-name + alias keys in the same dict — which extra='forbid'
        # rejects (see test above).
        existing = LLMSettings.model_validate({'model': 'gpt-4o-mini'})
        form = {'llm_change_summary_default': 'Saved global prompt.', 'llm_model': 'gpt-4o-mini'}
        merged = LLMSettings.model_validate({**existing.model_dump(by_alias=True), **form})
        self.assertEqual(merged.change_summary_default, 'Saved global prompt.')
        self.assertEqual(merged.model_dump()['change_summary_default'], 'Saved global prompt.')


class TestLLMSettingsTypeCoercion(unittest.TestCase):
    def test_select_field_string_int_coerces_to_int(self):
        # WTForms SelectField returns the choice key as a string ('500');
        # Pydantic must coerce to int so storage stays typed.
        s = LLMSettings.model_validate({'llm_thinking_budget': '500', 'llm_max_summary_tokens': '5000'})
        self.assertEqual(s.thinking_budget, 500)
        self.assertEqual(s.max_summary_tokens, 5000)

    def test_invalid_int_raises(self):
        with self.assertRaises(ValidationError):
            LLMSettings.model_validate({'llm_thinking_budget': 'not_a_number'})


class TestLLMSettingsExtraForbid(unittest.TestCase):
    def test_unknown_key_raises(self):
        # extra='forbid' is the security gate against CWE-915 mass-assignment.
        with self.assertRaises(ValidationError) as ctx:
            LLMSettings.model_validate({'llm_model': 'gpt-4o-mini', 'llm_evil_field': 'pwn'})
        self.assertIn('llm_evil_field', str(ctx.exception))

    def test_dunder_key_raises(self):
        with self.assertRaises(ValidationError):
            LLMSettings.model_validate({'llm_model': 'gpt-4o-mini', '__class__': 'attack'})

    def test_legitimate_unknown_key_also_raises(self):
        # No "future-tolerant" silent acceptance — new fields must be declared.
        with self.assertRaises(ValidationError):
            LLMSettings.model_validate({'maybe_future_counter': 42})


class TestLLMSettingsDumpShapes(unittest.TestCase):
    def test_dump_uses_stripped_field_names(self):
        s = LLMSettings.model_validate({'llm_model': 'gpt-4o-mini'})
        out = s.model_dump()
        self.assertIn('model', out)
        self.assertNotIn('llm_model', out)
        self.assertEqual(out['model'], 'gpt-4o-mini')

    def test_dump_by_alias_uses_prefixed_names(self):
        s = LLMSettings.model_validate({'model': 'gpt-4o-mini'})
        out = s.model_dump(by_alias=True)
        self.assertIn('llm_model', out)
        self.assertNotIn('model', out)
        self.assertEqual(out['llm_model'], 'gpt-4o-mini')

    def test_dump_exclude_connection_drops_provider_fields(self):
        s = LLMSettings.model_validate({
            'model': 'gpt-4o-mini', 'api_key': 'sk-test', 'api_base': 'https://example',
            'provider_kind': 'ollama', 'local_token_multiplier': 5,
            'enabled': False, 'tokens_this_month': 42,
        })
        out = s.model_dump(exclude=set(LLMSettings.CONNECTION_FIELDS))
        for k in LLMSettings.CONNECTION_FIELDS:
            self.assertNotIn(k, out, f"connection field {k} should be excluded")
        # Non-connection fields survive
        self.assertFalse(out['enabled'])
        self.assertEqual(out['tokens_this_month'], 42)


class TestLLMSettingsFieldGroups(unittest.TestCase):
    def test_connection_fields_all_declared(self):
        declared = set(LLMSettings.model_fields)
        for name in LLMSettings.CONNECTION_FIELDS:
            self.assertIn(name, declared, f"CONNECTION_FIELDS lists undeclared field: {name}")

    def test_protected_fields_all_declared(self):
        declared = set(LLMSettings.model_fields)
        for name in LLMSettings.PROTECTED_FIELDS:
            self.assertIn(name, declared, f"PROTECTED_FIELDS lists undeclared field: {name}")

    def test_connection_and_protected_disjoint(self):
        # System-managed counters and user-set provider config must not overlap —
        # otherwise a "clear credentials" action would also wipe counters.
        overlap = set(LLMSettings.CONNECTION_FIELDS) & set(LLMSettings.PROTECTED_FIELDS)
        self.assertEqual(overlap, set(), f"CONNECTION/PROTECTED overlap: {overlap}")


class TestLLMSettingsRoundTrip(unittest.TestCase):
    def test_counter_round_trip_via_dump_load(self):
        original = LLMSettings.model_validate({
            'model': 'gpt-4o-mini',
            'tokens_total_cumulative': 123456,
            'tokens_this_month': 789,
            'tokens_month_key': '2026-05',
            'cost_usd_total_cumulative': 12.34,
            'cost_usd_this_month': 0.56,
        })
        roundtripped = LLMSettings.model_validate(original.model_dump())
        self.assertEqual(roundtripped.tokens_total_cumulative, 123456)
        self.assertEqual(roundtripped.tokens_this_month, 789)
        self.assertEqual(roundtripped.tokens_month_key, '2026-05')
        self.assertEqual(roundtripped.cost_usd_total_cumulative, 12.34)
        self.assertEqual(roundtripped.cost_usd_this_month, 0.56)

    def test_form_merge_preserves_counters(self):
        # The POST handler pattern: validate existing storage, overlay form input
        # (with PROTECTED_FIELDS stripped), re-validate. Counters in storage must
        # survive even if the form somehow tried to set them.
        existing = LLMSettings.model_validate({
            'model': 'gpt-4o-mini', 'tokens_total_cumulative': 99999,
        })
        form_input = {
            'llm_model': 'claude-3-5-haiku-20251001',
            'llm_enabled': False,
        }
        # Strip protected fields from form input as the route handler does
        for protected in LLMSettings.PROTECTED_FIELDS:
            form_input.pop(protected, None)
        merged = LLMSettings.model_validate(
            {**existing.model_dump(by_alias=True), **form_input}
        )
        self.assertEqual(merged.model, 'claude-3-5-haiku-20251001')
        self.assertFalse(merged.enabled)
        self.assertEqual(merged.tokens_total_cumulative, 99999)


if __name__ == '__main__':
    unittest.main()
