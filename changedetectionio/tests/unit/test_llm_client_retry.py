import unittest
from unittest.mock import MagicMock, call, patch
import litellm

from changedetectionio.llm import client as m


class TestLLMClientRetryHandling(unittest.TestCase):
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

    def _make_error(self, err_cls, message="Transient error"):
        return err_cls(
            message=message,
            model="gemini/gemini-2.5-flash",
            llm_provider="gemini",
            response=MagicMock(),
        )

    @patch("time.sleep")
    def test_retry_on_service_unavailable_succeeds(self, mock_sleep):
        exc = self._make_error(litellm.ServiceUnavailableError, "503 Service Unavailable")
        mock_resp = self._mock_success_response("recovered response")

        with patch("litellm.completion", side_effect=[exc, mock_resp]) as mock_call:
            text, total_tok, in_tok, out_tok = m.completion(
                model="gemini/gemini-2.5-flash",
                messages=[{"role": "user", "content": "hello"}],
            )
            self.assertEqual(text, "recovered response")
            self.assertEqual(mock_call.call_count, 2)
            mock_sleep.assert_called_once_with(1)

    @patch("time.sleep")
    def test_retry_on_rate_limit_succeeds(self, mock_sleep):
        exc = self._make_error(litellm.RateLimitError, "429 Rate limit reached")
        mock_resp = self._mock_success_response("recovered after rate limit")

        with patch("litellm.completion", side_effect=[exc, mock_resp]) as mock_call:
            text, total_tok, in_tok, out_tok = m.completion(
                model="gemini/gemini-2.5-flash",
                messages=[{"role": "user", "content": "hello"}],
            )
            self.assertEqual(text, "recovered after rate limit")
            self.assertEqual(mock_call.call_count, 2)
            mock_sleep.assert_called_once_with(1)

    @patch("time.sleep")
    def test_retry_on_internal_server_error_succeeds(self, mock_sleep):
        exc = self._make_error(litellm.InternalServerError, "500 Internal Server Error")
        mock_resp = self._mock_success_response("recovered from 500")

        with patch("litellm.completion", side_effect=[exc, mock_resp]) as mock_call:
            text, _, _, _ = m.completion(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "hello"}],
            )
            self.assertEqual(text, "recovered from 500")
            self.assertEqual(mock_call.call_count, 2)
            mock_sleep.assert_called_once_with(1)

    @patch("time.sleep")
    def test_retry_exhausted_raises_after_default_retries(self, mock_sleep):
        exc = self._make_error(litellm.ServiceUnavailableError, "503 persistent overload")

        with patch("litellm.completion", side_effect=exc) as mock_call:
            with self.assertRaises(litellm.ServiceUnavailableError):
                m.completion(
                    model="gemini/gemini-2.5-flash",
                    messages=[{"role": "user", "content": "hello"}],
                )
            self.assertEqual(mock_call.call_count, m.DEFAULT_RETRIES)
            self.assertEqual(mock_sleep.call_count, m.DEFAULT_RETRIES - 1)
            self.assertEqual(mock_sleep.call_args_list, [call(1), call(2)])

    @patch("time.sleep")
    def test_non_retryable_error_raises_immediately(self, mock_sleep):
        exc = self._make_error(litellm.AuthenticationError, "401 Invalid API key")

        with patch("litellm.completion", side_effect=exc) as mock_call:
            with self.assertRaises(litellm.AuthenticationError):
                m.completion(
                    model="gemini/gemini-2.5-flash",
                    messages=[{"role": "user", "content": "hello"}],
                )
            self.assertEqual(mock_call.call_count, 1)
            mock_sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
