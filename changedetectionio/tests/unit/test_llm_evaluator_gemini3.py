#!/usr/bin/env python3
"""
Unit tests for changedetectionio.llm.evaluator:

  * _thinking_extra_body() sends no generationConfig at all for Gemini 3.x
    models (thinkingBudget is deprecated there and gets rejected outright),
    while still sending it for older Gemini generations that support it.
  * evaluate_change() marks its fail-open {'important': True, ...} fallback
    with 'llm_error': True when the LLM call itself raised, so a genuine
    outage (bad model/params, provider error, ...) is distinguishable from a
    real positive verdict — see the bug report this fixes: a total LLM
    outage against a Gemini 3.x lite model was silently indistinguishable
    from working intent-matching.

Run from the tests/ directory:
    python -m unittest unit/test_llm_evaluator_gemini3.py
"""
import unittest
from unittest.mock import patch

from changedetectionio.llm import evaluator as m


class FakeDatastore:
    def __init__(self, llm_cfg=None):
        self.data = {
            'settings': {
                'application': {
                    'llm': llm_cfg or {'model': 'gemini/gemini-3.5-flash-lite', 'api_key': 'test-key'},
                }
            }
        }
        self.commit_calls = 0

    def commit(self):
        self.commit_calls += 1


class TestThinkingExtraBodyGemini3(unittest.TestCase):
    def test_gemini_3_lite_gets_no_thinking_config(self):
        self.assertIsNone(m._thinking_extra_body('gemini/gemini-3.5-flash-lite', budget=0))

    def test_gemini_3_pro_gets_no_thinking_config(self):
        self.assertIsNone(m._thinking_extra_body('gemini/gemini-3-pro-preview', budget=1024))

    def test_non_gemini_model_gets_no_thinking_config(self):
        self.assertIsNone(m._thinking_extra_body('gpt-4o-mini', budget=1024))

    @patch('litellm.get_model_info')
    def test_older_gemini_that_supports_reasoning_still_gets_thinking_config(self, mock_info):
        mock_info.return_value = {'supports_reasoning': True}
        result = m._thinking_extra_body('gemini/gemini-2.5-flash', budget=512)
        self.assertEqual(result, {'generationConfig': {'thinkingConfig': {'thinkingBudget': 512}}})

    @patch('litellm.get_model_info')
    def test_older_gemini_without_reasoning_support_gets_none(self, mock_info):
        mock_info.return_value = {'supports_reasoning': False}
        self.assertIsNone(m._thinking_extra_body('gemini/gemini-1.5-flash', budget=512))


class TestEvaluateChangeLLMErrorMarker(unittest.TestCase):
    """A failed LLM call must be distinguishable from a genuine 'important' verdict."""

    def _watch(self, **overrides):
        watch = {
            'uuid': 'test-uuid',
            'llm_intent': 'Notify only on price changes',
            'tags': [],
        }
        watch.update(overrides)
        return watch

    def test_llm_call_failure_sets_llm_error_true(self):
        ds = FakeDatastore()
        watch = self._watch()
        with patch('changedetectionio.llm.evaluator.llm_client.completion',
                   side_effect=RuntimeError('simulated 400 INVALID_ARGUMENT')):
            result = m.evaluate_change(watch, ds, diff='- old price\n+ new price')

        self.assertEqual(result['important'], True)  # fail-open: notification still fires
        self.assertEqual(result['llm_error'], True)   # ...but is flagged as not a real verdict

    def test_successful_call_has_no_llm_error_flag(self):
        ds = FakeDatastore()
        watch = self._watch()
        with patch('changedetectionio.llm.evaluator.llm_client.completion',
                   return_value=('{"important": true, "summary": "price changed"}', 42, 30, 12)):
            result = m.evaluate_change(watch, ds, diff='- old price\n+ new price')

        self.assertEqual(result['important'], True)
        self.assertNotIn('llm_error', result)

    def test_budget_exceeded_fail_open_is_not_marked_as_error(self):
        ds = FakeDatastore(llm_cfg={
            'model': 'gemini/gemini-3.5-flash-lite',
            'api_key': 'test-key',
            'token_budget_month': 100,
            'tokens_this_month': 1000,
            'tokens_month_key': m._get_month_key(),
        })
        watch = self._watch()
        result = m.evaluate_change(watch, ds, diff='- old price\n+ new price')

        self.assertEqual(result['important'], True)
        self.assertEqual(result.get('llm_error'), False)
        self.assertEqual(result.get('llm_skipped'), 'budget_exceeded')


if __name__ == '__main__':
    unittest.main()
