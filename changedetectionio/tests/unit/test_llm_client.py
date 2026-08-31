#!/usr/bin/env python3
"""
Unit tests for changedetectionio.llm.client:

  * is_gemini_3_family() correctly identifies Gemini 3.x models with/without
    a provider prefix, and doesn't false-positive on other Gemini generations.
  * completion() omits 'temperature' for Gemini 3.x models (which reject it
    outright) but still sends it for every other model.
  * The BadRequestError strip-and-retry fallback fires even when the
    provider's error message doesn't name the offending field (Google's
    Gemini 3.x 400 INVALID_ARGUMENT responses carry no 'details' field), and
    strips both sampling params (kwargs) and Gemini's
    generationConfig.thinkingConfig (extra_body).
  * The fallback only retries once — a second BadRequestError with nothing
    left to strip propagates instead of looping.

Run from the tests/ directory:
    python -m unittest unit/test_llm_client.py
"""
import unittest
from unittest.mock import patch, MagicMock

from changedetectionio.llm import client as m


def _mock_success_response(text='{"important": true, "summary": "ok"}'):
    message = MagicMock()
    message.content = text
    message.parts = None
    choice = MagicMock()
    choice.message = message
    choice.finish_reason = 'stop'
    response = MagicMock()
    response.choices = [choice]
    response.usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    return response


class TestIsGemini3Family(unittest.TestCase):
    def test_gemini_3_with_provider_prefix(self):
        self.assertTrue(m.is_gemini_3_family('gemini/gemini-3.5-flash-lite'))
        self.assertTrue(m.is_gemini_3_family('gemini/gemini-3-pro-preview'))

    def test_gemini_3_without_provider_prefix(self):
        self.assertTrue(m.is_gemini_3_family('gemini-3.5-flash-lite'))

    def test_vertex_ai_prefix(self):
        self.assertTrue(m.is_gemini_3_family('vertex_ai/gemini-3.5-flash-lite'))

    def test_older_gemini_not_matched(self):
        self.assertFalse(m.is_gemini_3_family('gemini/gemini-2.5-flash'))
        self.assertFalse(m.is_gemini_3_family('gemini/gemini-1.5-pro'))

    def test_non_gemini_model_not_matched(self):
        self.assertFalse(m.is_gemini_3_family('gpt-4o-mini'))
        self.assertFalse(m.is_gemini_3_family('claude-opus-4-8'))

    def test_empty_or_none(self):
        self.assertFalse(m.is_gemini_3_family(''))
        self.assertFalse(m.is_gemini_3_family(None))


class TestCompletionTemperatureHandling(unittest.TestCase):
    """completion() must not send 'temperature' to Gemini 3.x models."""

    def test_temperature_sent_for_non_gemini_3_model(self):
        with patch('litellm.completion', return_value=_mock_success_response()) as mock_call:
            m.completion(model='gemini/gemini-2.5-flash', messages=[{'role': 'user', 'content': 'hi'}])
            self.assertIn('temperature', mock_call.call_args.kwargs)
            self.assertEqual(mock_call.call_args.kwargs['temperature'], 0)

    def test_temperature_omitted_for_gemini_3_model(self):
        with patch('litellm.completion', return_value=_mock_success_response()) as mock_call:
            m.completion(model='gemini/gemini-3.5-flash-lite', messages=[{'role': 'user', 'content': 'hi'}])
            self.assertNotIn('temperature', mock_call.call_args.kwargs)


class TestBadRequestStripAndRetry(unittest.TestCase):
    """
    Google's Gemini 3.x 400 INVALID_ARGUMENT responses don't name the
    offending field, so the fallback must not depend on message-matching —
    only on there being something of ours left to strip.
    """

    def _bad_request(self, msg='Request contains an invalid argument.'):
        import litellm as real_litellm
        return real_litellm.BadRequestError(msg, llm_provider='gemini', model='gemini/gemini-3.5-flash-lite')

    def test_retries_and_succeeds_after_stripping_thinking_config(self):
        exc = self._bad_request()
        success = _mock_success_response()
        with patch('litellm.completion', side_effect=[exc, success]) as mock_call:
            text, tokens, *_ = m.completion(
                model='gemini/gemini-3.5-flash-lite',
                messages=[{'role': 'user', 'content': 'hi'}],
                extra_body={'generationConfig': {'thinkingConfig': {'thinkingBudget': 0}}},
            )
        self.assertEqual(mock_call.call_count, 2)
        # The second (retried) call must no longer carry thinkingConfig.
        second_call_kwargs = mock_call.call_args_list[1].kwargs
        self.assertNotIn('extra_body', second_call_kwargs)
        self.assertIn('important', text)

    def test_retries_and_strips_sampling_params_generic_message(self):
        # No mention of 'temperature' anywhere in the message — this is what
        # trips up the old message-matching implementation.
        exc = self._bad_request(msg='Request contains an invalid argument.')
        success = _mock_success_response()
        with patch('litellm.completion', side_effect=[exc, success]) as mock_call:
            m.completion(
                model='gemini/gemini-2.5-flash',  # not gemini-3, so temperature is set by default
                messages=[{'role': 'user', 'content': 'hi'}],
            )
        self.assertEqual(mock_call.call_count, 2)
        first_call_kwargs = mock_call.call_args_list[0].kwargs
        second_call_kwargs = mock_call.call_args_list[1].kwargs
        self.assertIn('temperature', first_call_kwargs)
        self.assertNotIn('temperature', second_call_kwargs)

    def test_does_not_loop_when_nothing_left_to_strip(self):
        # Two BadRequestErrors in a row, no sampling params / extra_body present
        # at all — nothing to strip, so the second attempt is never made and the
        # original error propagates rather than retrying forever.
        exc = self._bad_request('some other, unrelated 400 error')
        with patch('litellm.completion', side_effect=exc) as mock_call:
            with self.assertRaises(type(exc)):
                m.completion(
                    model='gemini/gemini-3.5-flash-lite',  # temperature already omitted -> nothing to strip
                    messages=[{'role': 'user', 'content': 'hi'}],
                )
        self.assertEqual(mock_call.call_count, 1)

    def test_only_retries_once(self):
        # If stripping doesn't fix it, the second BadRequestError (now with
        # nothing left of ours to strip) must propagate, not retry again.
        exc1 = self._bad_request()
        exc2 = self._bad_request('still invalid')
        with patch('litellm.completion', side_effect=[exc1, exc2]) as mock_call:
            with self.assertRaises(type(exc2)):
                m.completion(
                    model='gemini/gemini-2.5-flash',
                    messages=[{'role': 'user', 'content': 'hi'}],
                    extra_body={'generationConfig': {'thinkingConfig': {'thinkingBudget': 0}}},
                )
        self.assertEqual(mock_call.call_count, 2)


if __name__ == '__main__':
    unittest.main()
