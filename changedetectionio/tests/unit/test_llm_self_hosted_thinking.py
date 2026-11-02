#!/usr/bin/env python3

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_llm_self_hosted_thinking
"""
"Switch thinking off" for Ollama and OpenAI-compatible servers (llama.cpp, vLLM, LM Studio), #4638.
Its own opt-in, not the thinking budget, which defaults to Off.
"""
import unittest

from changedetectionio.llm import evaluator as ev
from changedetectionio.model.LLMSettings import LLMSettings


class TestSelfHostedThinkingOff(unittest.TestCase):
    def test_default_sends_nothing(self):
        self.assertFalse(LLMSettings.model_validate({}).local_thinking_off)
        for kind in ('ollama', 'openai_compatible'):
            for budget in (0, 2000):
                self.assertIsNone(ev._thinking_extra_body('openai/lfm3', budget, {'provider_kind': kind}))

    def test_switched_off(self):
        self.assertEqual(ev._thinking_extra_body('ollama/qwen3', 0, {'provider_kind': 'ollama', 'local_thinking_off': True}),
                         {'think': False})
        self.assertEqual(ev._thinking_extra_body('openai/lfm3', 0, {'provider_kind': 'openai_compatible', 'local_thinking_off': True}),
                         {'chat_template_kwargs': {'enable_thinking': False}})

    def test_cloud_never(self):
        for model in ('gpt-4o', 'openai/gpt-4o'):
            self.assertIsNone(ev._thinking_extra_body(model, 0, {'provider_kind': '', 'local_thinking_off': True}))


if __name__ == '__main__':
    unittest.main()
