#!/usr/bin/env python3

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_llm_claude_thinking
"""
Thinking budget Off (0) switches thinking off for Claude models that think by default (Claude 5.x).
"""
import unittest
from unittest.mock import MagicMock, patch

from changedetectionio.llm import client as m
from changedetectionio.llm import evaluator as ev

DISABLED = {'thinking': {'type': 'disabled'}}
ADAPTIVE = {'supports_adaptive_thinking': True, 'thinking_always_on': False}


@patch('litellm.get_model_info', return_value=ADAPTIVE)
class TestClaudeThinkingOff(unittest.TestCase):
    def test_claude_5_off(self, _info):
        for model in ('anthropic/claude-haiku-5-5', 'anthropic/claude-sonnet-5', 'claude-haiku-5-5'):
            self.assertEqual(ev._thinking_extra_body(model, 0), DISABLED, model)

    def test_sonnet_5_5_uses_between_tools(self, _info):
        self.assertEqual(ev._thinking_extra_body('anthropic/claude-sonnet-5-5', 0),
                         {'thinking': {'type': 'between_tools'}})

    def test_budget_keeps_provider_default(self, _info):
        # Claude 5.x has no thinking token budget, budget_tokens is a 400
        self.assertIsNone(ev._thinking_extra_body('anthropic/claude-haiku-5-5', 500))

    def test_left_alone(self, _info):
        # Opus 5 leaks <thinking> tags with thinking disabled, Opus 5.5 / Fable can't switch it off, 4.x doesn't think
        for model in ('anthropic/claude-opus-5', 'anthropic/claude-opus-5-5', 'anthropic/claude-fable-5-1',
                      'anthropic/claude-haiku-4-5-20251001', 'anthropic/claude-sonnet-4-6'):
            self.assertIsNone(ev._thinking_extra_body(model, 0), model)

    def test_registry_says_always_on(self, info):
        info.return_value = {'supports_adaptive_thinking': True, 'thinking_always_on': True}
        self.assertIsNone(ev._thinking_extra_body('anthropic/claude-haiku-5-9', 0))

    def test_unknown_model_untouched(self, info):
        info.side_effect = Exception('unknown')
        self.assertIsNone(ev._thinking_extra_body('anthropic/claude-haiku-5-9', 0))

    def test_other_providers_unchanged(self, _info):
        self.assertIsNone(ev._thinking_extra_body('gpt-4o-mini', 0))
        self.assertIsNone(ev._thinking_extra_body('openrouter/anthropic/claude-haiku-5-5', 0))
        self.assertEqual(ev._thinking_extra_body('ollama/qwen3', 0, {'provider_kind': 'ollama', 'local_thinking_off': True}),
                         {'think': False})


class TestClientLiftsThinking(unittest.TestCase):
    def _resp(self):
        r = MagicMock()
        r.choices = [MagicMock(message=MagicMock(content='{}', parts=None), finish_reason='stop')]
        return r

    def _bad_request(self, message):
        import litellm
        return litellm.BadRequestError(message=message, model='x', llm_provider='anthropic', response=MagicMock(status_code=400))

    def test_thinking_is_top_level_not_extra_body(self):
        with patch('litellm.completion', return_value=self._resp()) as call:
            m.completion(model='anthropic/claude-haiku-5-5', messages=[], extra_body=DISABLED)
        kwargs = call.call_args.kwargs
        self.assertEqual(kwargs['thinking'], {'type': 'disabled'})
        self.assertNotIn('extra_body', kwargs)

    def test_only_lifted_for_anthropic(self):
        with patch('litellm.completion', return_value=self._resp()) as call:
            m.completion(model='openai/glm-5', messages=[], extra_body=DISABLED)
        kwargs = call.call_args.kwargs
        self.assertNotIn('thinking', kwargs)
        self.assertEqual(kwargs['extra_body'], DISABLED)

    def test_bad_request_about_thinking_drops_it_and_retries(self):
        exc = self._bad_request('thinking.type: Input should be adaptive')
        with patch('litellm.completion', side_effect=[exc, self._resp()]) as call:
            m.completion(model='anthropic/claude-haiku-5-5', messages=[], extra_body=DISABLED)
        self.assertEqual(call.call_count, 2)
        self.assertNotIn('thinking', call.call_args_list[1].kwargs)

    def test_unrelated_bad_request_not_retried(self):
        exc = self._bad_request('prompt is too long')
        with patch('litellm.completion', side_effect=exc) as call:
            with self.assertRaises(Exception):
                m.completion(model='anthropic/claude-haiku-5-5', messages=[], extra_body=DISABLED)
        self.assertEqual(call.call_count, 1)


if __name__ == '__main__':
    unittest.main()
