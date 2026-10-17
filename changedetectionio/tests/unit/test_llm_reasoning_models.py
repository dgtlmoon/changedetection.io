#!/usr/bin/env python3
"""
Reasoning models need two things the others don't: no `temperature`, and enough
`max_tokens` headroom for chain-of-thought to finish before the answer starts.

The client strips sampling params and retries when a provider rejects them (#4342), so a
missing entry here is not fatal - it just means every single call to that model pays a
rejected round trip first, and logs a warning each time. gpt-5 was named in the code comment
but never added to the list, so that is exactly what it did.

Equally, listing a model that DOES accept temperature is not free: we would silently stop
sending temperature=0 and get less deterministic output with no error to notice.
"""
import unittest

from changedetectionio.llm.client import _NO_TEMPERATURE_MODEL_KEYWORDS
from changedetectionio.llm.evaluator import apply_local_token_multiplier


def _sends_temperature(model: str) -> bool:
    return not any(k in (model or '').lower() for k in _NO_TEMPERATURE_MODEL_KEYWORDS)


class TestTemperatureModelMatching(unittest.TestCase):

    def test_reasoning_models_do_not_get_temperature(self):
        for model in ('gpt-5', 'openai/gpt-5', 'gpt-5-mini', 'gpt-5.1',
                      'o1', 'o1-mini', 'o3', 'o3-mini', 'o4-mini',
                      'gemini/gemini-2.0-flash-lite', 'gemini-2.0-thinking-exp'):
            self.assertFalse(_sends_temperature(model),
                             f"{model} rejects temperature; sending it costs a retry on every call")

    def test_ordinary_models_still_get_temperature(self):
        """Over-matching is the quieter failure: no error, just non-deterministic output."""
        for model in ('gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-3.5-turbo',
                      'claude-sonnet-5', 'gemini/gemini-2.0-flash',
                      'ollama/llama3', 'ollama/mistral', 'ollama/gemma3'):
            self.assertTrue(_sends_temperature(model),
                            f"{model} accepts temperature - dropping it loses determinism silently")


if __name__ == '__main__':
    unittest.main()


class TestReasoningTokenHeadroom(unittest.TestCase):
    """Reasoning tokens are billed AND counted against max_tokens.

    gpt-5 on the old tight 400 cap spent all 400 on reasoning, returned content='' with
    finish_reason='length', and still charged for the call - every summary empty, every
    summary paid for. The headroom used to key on the endpoint being local, but what
    actually matters is whether the model reasons.
    """

    def test_cloud_reasoning_models_get_headroom(self):
        for model in ('gpt-5', 'gpt-5-mini', 'o1', 'o3-mini', 'o4-mini'):
            got = apply_local_token_multiplier(400, {'model': model, 'provider_kind': 'openai'})
            self.assertGreater(got, 400, f"{model} reasons; 400 tokens is consumed before it answers")

    def test_non_reasoning_cloud_models_are_unchanged(self):
        """Raising these would silently increase everyone's bill for no benefit."""
        for model, kind in (('gpt-4o', 'openai'), ('gpt-4-turbo', 'openai'),
                            ('claude-sonnet-5', 'anthropic'), ('gemini-2.0-flash', 'gemini')):
            self.assertEqual(400, apply_local_token_multiplier(400, {'model': model,
                                                                     'provider_kind': kind}))

    def test_local_endpoints_keep_their_existing_headroom(self):
        self.assertEqual(2000, apply_local_token_multiplier(
            400, {'model': 'llama3', 'provider_kind': 'ollama'}))

    def test_multiplier_is_still_clamped(self):
        got = apply_local_token_multiplier(400, {'model': 'gpt-5', 'provider_kind': 'openai',
                                                 'local_token_multiplier': 9999})
        self.assertEqual(400 * 20, got, "a corrupted multiplier must stay clamped")
