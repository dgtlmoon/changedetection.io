#!/usr/bin/env python3

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_llm_self_hosted_thinking
"""
"Switch thinking off" for self-hosted servers: Ollama, and OpenAI-compatible ones (llama.cpp, vLLM, LM Studio), #4638.

It's an opt-in of its own, NOT the thinking budget: the budget defaults to Off (0), so following it would have
switched thinking off for every existing self-hosted user.
"""
import copy
import unittest
from unittest.mock import MagicMock, patch

from changedetectionio.llm import client as m
from changedetectionio.llm import evaluator as ev
from changedetectionio.model.LLMSettings import LLMSettings, LLM_DEFAULT_THINKING_BUDGET


def _cfg(**kw):
    return {'model': 'openai/lfm3-1.7b', 'provider_kind': 'openai_compatible', **kw}


class TestSelfHostedThinkingExtraBody(unittest.TestCase):
    def test_default_sends_nothing(self):
        # Existing users: default budget (Off) and the new switch unset, nothing changes for them
        self.assertFalse(LLMSettings.model_validate({}).local_thinking_off)
        for budget in (LLM_DEFAULT_THINKING_BUDGET, 0, 500, 2000):
            self.assertIsNone(ev._thinking_extra_body('openai/lfm3-1.7b', budget, _cfg()))

    def test_ollama_switched_off(self):
        cfg = {'model': 'ollama/qwen3', 'provider_kind': 'ollama'}
        self.assertIsNone(ev._thinking_extra_body('ollama/qwen3', 0, cfg))
        self.assertEqual(ev._thinking_extra_body('ollama/qwen3', 0, {**cfg, 'local_thinking_off': True}),
                         {'think': False})

    def test_switched_off_sends_both_switches_whatever_the_budget(self):
        for budget in (0, 2000):
            self.assertEqual(ev._thinking_extra_body('openai/lfm3-1.7b', budget, _cfg(local_thinking_off=True)),
                             {'reasoning_effort': 'none', 'chat_template_kwargs': {'enable_thinking': False}})

    def test_returns_a_copy(self):
        # client.completion() pops keys from it on a 400 retry, that must not change the constant
        body = ev._thinking_extra_body('openai/x', 0, _cfg(local_thinking_off=True))
        body.pop('reasoning_effort')
        self.assertIn('reasoning_effort', ev.SELF_HOSTED_THINKING_OFF['openai_compatible'])

    def test_only_self_hosted(self):
        # Cloud providers never get it, even with the switch left on from an earlier provider
        for kind, model in (('', 'gpt-4o'), ('', 'openai/gpt-4o'), ('openrouter', 'openrouter/qwen/qwen3')):
            self.assertIsNone(ev._thinking_extra_body(model, 0, {'model': model, 'provider_kind': kind,
                                                                 'local_thinking_off': True}))

    def test_gemini_unchanged(self):
        with patch('litellm.get_model_info', return_value={'supports_reasoning': True}):
            self.assertEqual(ev._thinking_extra_body('gemini/gemini-2.5-flash', 500, {'provider_kind': ''}),
                             {'generationConfig': {'thinkingConfig': {'thinkingBudget': 500}}})
            self.assertEqual(ev._thinking_extra_body('gemini/gemini-2.5-flash', 500),
                             {'generationConfig': {'thinkingConfig': {'thinkingBudget': 500}}})

    def test_cleared_with_the_connection(self):
        self.assertIn('local_thinking_off', LLMSettings.CONNECTION_FIELDS)


class TestSelfHostedThinkingRejected(unittest.TestCase):
    """A server that doesn't know the switches and answers 400: retried once without them."""

    def _ok(self):
        resp = MagicMock()
        resp.choices = [MagicMock(message=MagicMock(content='ok', parts=None), finish_reason='stop')]
        resp.usage = MagicMock(total_tokens=3, prompt_tokens=2, completion_tokens=1)
        return resp

    def test_stripped_and_retried(self):
        import litellm
        bad = litellm.BadRequestError(message="Unrecognized request argument supplied: reasoning_effort",
                                      model='openai/x', llm_provider='openai', response=MagicMock(status_code=400))
        sent, answers = [], [bad, self._ok()]

        def fake_completion(**kwargs):
            # A deep copy as sent: the retry strips keys from the same extra_body dict
            sent.append(copy.deepcopy(kwargs))
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        with patch('litellm.completion', side_effect=fake_completion):
            text, *_ = m.completion(model='openai/x', messages=[{'role': 'user', 'content': 'hi'}],
                                    api_base='http://127.0.0.1:8080/v1',
                                    extra_body=ev._thinking_extra_body('openai/x', 0, _cfg(local_thinking_off=True)))
        self.assertEqual(text, 'ok')
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0]['extra_body'], ev.SELF_HOSTED_THINKING_OFF['openai_compatible'])
        self.assertNotIn('extra_body', sent[1])


if __name__ == '__main__':
    unittest.main()
