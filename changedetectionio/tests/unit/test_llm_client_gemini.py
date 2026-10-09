import unittest
from unittest.mock import MagicMock, patch

from changedetectionio.llm import client as m
from changedetectionio.llm import evaluator as ev


class TestGeminiFlashLiteClientHandling(unittest.TestCase):
    def _mock_success_response(
        self, text="test response", total_tokens=50, input_tokens=30, output_tokens=20
    ):
        mock_resp = MagicMock()
        mock_resp.choices = [
            MagicMock(message=MagicMock(content=text, parts=None), finish_reason="stop")
        ]
        mock_usage = MagicMock()
        mock_usage.total_tokens = total_tokens
        mock_usage.prompt_tokens = input_tokens
        mock_usage.completion_tokens = output_tokens
        mock_resp.usage = mock_usage
        return mock_resp

    def _bad_request(self, message="Request contains an invalid argument."):
        import litellm

        return litellm.BadRequestError(
            message=message,
            model="gemini/gemini-2.0-flash-lite",
            llm_provider="gemini",
            response=MagicMock(status_code=400),
        )

    def test_flash_lite_model_omits_temperature_initially(self):
        mock_resp = self._mock_success_response()
        with patch("litellm.completion", return_value=mock_resp) as mock_call:
            text, total_tok, in_tok, out_tok = m.completion(
                model="gemini/gemini-2.0-flash-lite",
                messages=[{"role": "user", "content": "hi"}],
            )
            self.assertEqual(text, "test response")
            self.assertEqual(total_tok, 50)
            self.assertEqual(in_tok, 30)
            self.assertEqual(out_tok, 20)

        kwargs = mock_call.call_args.kwargs
        self.assertNotIn("temperature", kwargs)

    def test_standard_model_includes_temperature_zero(self):
        mock_resp = self._mock_success_response()
        with patch("litellm.completion", return_value=mock_resp) as mock_call:
            m.completion(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "hi"}],
            )
        kwargs = mock_call.call_args.kwargs
        self.assertEqual(kwargs.get("temperature"), 0)

    def test_bad_request_strips_temperature_and_extra_body_and_retries(self):
        exc = self._bad_request()
        mock_resp = self._mock_success_response()
        with patch("litellm.completion", side_effect=[exc, mock_resp]) as mock_call:
            text, total_tok, in_tok, out_tok = m.completion(
                model="gemini/gemini-2.5-flash",
                messages=[{"role": "user", "content": "hi"}],
                extra_body={"generationConfig": {"thinkingConfig": {"thinkingBudget": 0}}},
            )
            self.assertEqual(text, "test response")
            self.assertEqual(mock_call.call_count, 2)

            first_call_kwargs = mock_call.call_args_list[0].kwargs
            second_call_kwargs = mock_call.call_args_list[1].kwargs

            self.assertIn("temperature", first_call_kwargs)
            self.assertIn("extra_body", first_call_kwargs)
            self.assertNotIn("temperature", second_call_kwargs)
            self.assertNotIn("extra_body", second_call_kwargs)

    def test_does_not_infinite_loop_when_nothing_left_to_strip(self):
        exc = self._bad_request("another 400 error")
        with patch("litellm.completion", side_effect=exc) as mock_call:
            with self.assertRaises(type(exc)):
                m.completion(
                    model="gemini/gemini-2.0-flash-lite",
                    messages=[{"role": "user", "content": "hi"}],
                )
        self.assertEqual(mock_call.call_count, 1)

    def test_only_retries_once_on_persistent_400(self):
        exc1 = self._bad_request("first 400")
        exc2 = self._bad_request("second 400")
        with patch("litellm.completion", side_effect=[exc1, exc2]) as mock_call:
            with self.assertRaises(type(exc2)):
                m.completion(
                    model="gemini/gemini-2.5-flash",
                    messages=[{"role": "user", "content": "hi"}],
                    extra_body={"generationConfig": {"thinkingConfig": {"thinkingBudget": 0}}},
                )
        self.assertEqual(mock_call.call_count, 2)


class TestThinkingExtraBodyFlashLite(unittest.TestCase):
    def test_flash_lite_model_gets_no_thinking_config(self):
        self.assertIsNone(ev._thinking_extra_body("gemini/gemini-2.0-flash-lite", budget=0))
        self.assertIsNone(ev._thinking_extra_body("gemini/gemini-3.5-flash-lite", budget=0))

    def test_non_gemini_model_gets_no_thinking_config(self):
        self.assertIsNone(ev._thinking_extra_body("gpt-4o-mini", budget=100))

    @patch("litellm.get_model_info")
    def test_gemini_supporting_reasoning_gets_thinking_config(self, mock_info):
        mock_info.return_value = {"supports_reasoning": True}
        result = ev._thinking_extra_body("gemini/gemini-2.5-flash", budget=512)
        self.assertEqual(result, {"generationConfig": {"thinkingConfig": {"thinkingBudget": 512}}})


if __name__ == "__main__":
    unittest.main()
