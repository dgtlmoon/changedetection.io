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

    def _make_error(self, err_cls, message="Transient error", headers=None, retry_after=None):
        mock_resp = MagicMock()
        if headers is not None:
            mock_resp.headers = headers
        else:
            mock_resp.headers = {}
        err = err_cls(
            message=message,
            model="gemini/gemini-2.5-flash",
            llm_provider="gemini",
            response=mock_resp,
        )
        if retry_after is not None:
            err.retry_after = retry_after
        return err

    @patch("random.uniform", return_value=0.25)
    def test_get_retry_delay_from_exception_attribute(self, mock_jitter):
        exc = self._make_error(litellm.RateLimitError, retry_after=4)
        delay = m._get_retry_delay(exc, attempt=1)
        self.assertEqual(delay, 4.25)

    @patch("random.uniform", return_value=0.2)
    def test_get_retry_delay_from_response_headers(self, mock_jitter):
        exc = self._make_error(
            litellm.ServiceUnavailableError, headers={"retry-after": "6"}
        )
        delay = m._get_retry_delay(exc, attempt=1)
        self.assertEqual(delay, 6.2)

    def test_get_retry_delay_exceeding_max_delay_returns_none(self):
        exc = self._make_error(litellm.RateLimitError, retry_after=3600)
        delay = m._get_retry_delay(exc, attempt=1, max_delay=15.0)
        self.assertIsNone(delay)

    @patch("random.uniform", return_value=0.3)
    def test_get_retry_delay_within_max_delay(self, mock_jitter):
        exc = self._make_error(litellm.RateLimitError, retry_after=10)
        delay = m._get_retry_delay(exc, attempt=1, max_delay=15.0)
        self.assertEqual(delay, 10.3)

    @patch("random.uniform", return_value=0.15)
    def test_get_retry_delay_fallback_exponential(self, mock_jitter):
        exc = self._make_error(litellm.InternalServerError)
        delay1 = m._get_retry_delay(exc, attempt=1)
        delay2 = m._get_retry_delay(exc, attempt=2)
        delay3 = m._get_retry_delay(exc, attempt=3)

        self.assertEqual(delay1, 1.15)
        self.assertEqual(delay2, 2.15)
        self.assertEqual(delay3, 4.15)

    @patch("random.uniform", return_value=0.1)
    @patch("time.sleep")
    def test_retry_on_service_unavailable_succeeds(self, mock_sleep, mock_jitter):
        exc = self._make_error(litellm.ServiceUnavailableError, "503 Service Unavailable")
        mock_resp = self._mock_success_response("recovered response")

        with patch("litellm.completion", side_effect=[exc, mock_resp]) as mock_call:
            text, total_tok, in_tok, out_tok = m.completion(
                model="gemini/gemini-2.5-flash",
                messages=[{"role": "user", "content": "hello"}],
            )
            self.assertEqual(text, "recovered response")
            self.assertEqual(mock_call.call_count, 2)
            mock_sleep.assert_called_once_with(1.1)

    @patch("random.uniform", return_value=0.2)
    @patch("time.sleep")
    def test_retry_on_rate_limit_honors_retry_after(self, mock_sleep, mock_jitter):
        exc = self._make_error(
            litellm.RateLimitError,
            "429 Rate limit reached",
            headers={"retry-after": "5"},
        )
        mock_resp = self._mock_success_response("recovered after rate limit")

        with patch("litellm.completion", side_effect=[exc, mock_resp]) as mock_call:
            text, total_tok, in_tok, out_tok = m.completion(
                model="gemini/gemini-2.5-flash",
                messages=[{"role": "user", "content": "hello"}],
            )
            self.assertEqual(text, "recovered after rate limit")
            self.assertEqual(mock_call.call_count, 2)
            mock_sleep.assert_called_once_with(5.2)

    @patch("random.uniform", return_value=0.1)
    @patch("time.sleep")
    def test_retry_on_internal_server_error_succeeds(self, mock_sleep, mock_jitter):
        exc = self._make_error(litellm.InternalServerError, "500 Internal Server Error")
        mock_resp = self._mock_success_response("recovered from 500")

        with patch("litellm.completion", side_effect=[exc, mock_resp]) as mock_call:
            text, _, _, _ = m.completion(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "hello"}],
            )
            self.assertEqual(text, "recovered from 500")
            self.assertEqual(mock_call.call_count, 2)
            mock_sleep.assert_called_once_with(1.1)

    @patch("random.uniform", return_value=0.0)
    @patch("time.sleep")
    def test_retry_exhausted_raises_after_default_retries(self, mock_sleep, mock_jitter):
        exc = self._make_error(litellm.ServiceUnavailableError, "503 persistent overload")

        with patch("litellm.completion", side_effect=exc) as mock_call:
            with self.assertRaises(litellm.ServiceUnavailableError):
                m.completion(
                    model="gemini/gemini-2.5-flash",
                    messages=[{"role": "user", "content": "hello"}],
                )
            self.assertEqual(mock_call.call_count, m.DEFAULT_RETRIES)
            self.assertEqual(mock_sleep.call_count, m.DEFAULT_RETRIES - 1)
            self.assertEqual(mock_sleep.call_args_list, [call(1.0), call(2.0)])

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

    @patch("time.sleep")
    def test_retry_after_exceeding_max_delay_aborts_immediately(self, mock_sleep):
        exc = self._make_error(
            litellm.RateLimitError,
            "429 Rate limit reached",
            headers={"retry-after": "60"},
        )
        with patch("litellm.completion", side_effect=exc) as mock_call:
            with self.assertRaises(litellm.RateLimitError):
                m.completion(
                    model="gemini/gemini-2.5-flash",
                    messages=[{"role": "user", "content": "hello"}],
                )
            self.assertEqual(mock_call.call_count, 1)
            mock_sleep.assert_not_called()

    @patch("time.sleep")
    def test_completion_with_zero_retries_fails_immediately(self, mock_sleep):
        exc = self._make_error(
            litellm.RateLimitError,
            "429 Quota exhausted",
            headers={"retry-after": "5"},
        )
        with patch("litellm.completion", side_effect=exc) as mock_call:
            with self.assertRaises(litellm.RateLimitError):
                m.completion(
                    model="gemini/gemini-2.5-flash",
                    messages=[{"role": "user", "content": "hello"}],
                    retries=0,
                )
            self.assertEqual(mock_call.call_count, 1)
            mock_sleep.assert_not_called()

    @patch("random.uniform", return_value=0.1)
    @patch("time.sleep")
    def test_param_strip_does_not_consume_transient_retry_budget(
        self, mock_sleep, mock_jitter
    ):
        # Stripping sampling params refunds the attempt, so the whole transient
        # budget is still available afterwards: DEFAULT_RETRIES + 1 calls.
        bad_request = self._make_error(
            litellm.BadRequestError, "400 temperature is not supported"
        )
        unavailable = self._make_error(
            litellm.ServiceUnavailableError, "503 Service Unavailable"
        )
        mock_resp = self._mock_success_response("recovered after strip")

        with patch(
            "litellm.completion",
            side_effect=[bad_request, unavailable, unavailable, mock_resp],
        ) as mock_call:
            text, _, _, _ = m.completion(
                model="gemini/gemini-2.5-flash",
                messages=[{"role": "user", "content": "hello"}],
            )

        self.assertEqual(text, "recovered after strip")
        self.assertEqual(mock_call.call_count, m.DEFAULT_RETRIES + 1)
        self.assertEqual(mock_sleep.call_args_list, [call(1.1), call(2.1)])

        # The refund is only correct if the strip really happened: the first
        # call still carries temperature, the ones after it do not.
        self.assertEqual(mock_call.call_args_list[0].kwargs.get("temperature"), 0)
        for subsequent in mock_call.call_args_list[1:]:
            self.assertNotIn("temperature", subsequent.kwargs)

    @patch("time.sleep")
    def test_bad_request_after_param_strip_raises(self, mock_sleep):
        # The second 400 has nothing left to drop, so it propagates instead of
        # refunding another attempt.
        exc = self._make_error(litellm.BadRequestError, "400 invalid request")

        with patch("litellm.completion", side_effect=exc) as mock_call:
            with self.assertRaises(litellm.BadRequestError):
                m.completion(
                    model="gemini/gemini-2.5-flash",
                    messages=[{"role": "user", "content": "hello"}],
                )
            self.assertEqual(mock_call.call_count, 2)
            mock_sleep.assert_not_called()

    @patch("time.sleep")
    def test_bad_request_with_nothing_to_strip_raises_immediately(self, mock_sleep):
        # This o1-preview request carries no sampling params, so there is
        # nothing to drop and no attempt to refund.
        exc = self._make_error(litellm.BadRequestError, "400 unsupported parameter")

        with patch("litellm.completion", side_effect=exc) as mock_call:
            with self.assertRaises(litellm.BadRequestError):
                m.completion(
                    model="o1-preview",
                    messages=[{"role": "user", "content": "hello"}],
                )
            self.assertEqual(mock_call.call_count, 1)
            mock_sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
