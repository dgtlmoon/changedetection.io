import datetime
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

    def test_parse_retry_after_numeric(self):
        self.assertEqual(m._parse_retry_after(5), 5.0)
        self.assertEqual(m._parse_retry_after(3.5), 3.5)
        self.assertEqual(m._parse_retry_after("7"), 7.0)
        self.assertEqual(m._parse_retry_after(" 12.5 "), 12.5)
        self.assertIsNone(m._parse_retry_after(0))
        self.assertIsNone(m._parse_retry_after("-1"))
        self.assertIsNone(m._parse_retry_after(""))
        self.assertIsNone(m._parse_retry_after(None))
        self.assertIsNone(m._parse_retry_after("invalid"))

    def test_parse_retry_after_http_date(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        future = (now + datetime.timedelta(seconds=15)).strftime("%a, %d %b %Y %H:%M:%S GMT")
        past = (now - datetime.timedelta(seconds=10)).strftime("%a, %d %b %Y %H:%M:%S GMT")

        parsed_future = m._parse_retry_after(future)
        self.assertIsNotNone(parsed_future)
        self.assertTrue(10.0 <= parsed_future <= 16.0)

        parsed_past = m._parse_retry_after(past)
        self.assertIsNone(parsed_past)

    @patch("random.uniform", return_value=0.25)
    def test_calculate_backoff_from_exception_attribute(self, mock_jitter):
        exc = self._make_error(litellm.RateLimitError, retry_after=4)
        delay, is_ra = m._calculate_backoff(exc, attempt=1)
        self.assertTrue(is_ra)
        self.assertEqual(delay, 4.25)

    @patch("random.uniform", return_value=0.2)
    def test_calculate_backoff_from_response_headers(self, mock_jitter):
        exc = self._make_error(
            litellm.ServiceUnavailableError, headers={"retry-after": "6"}
        )
        delay, is_ra = m._calculate_backoff(exc, attempt=1)
        self.assertTrue(is_ra)
        self.assertEqual(delay, 6.2)

    @patch("random.uniform", return_value=0.3)
    def test_calculate_backoff_capped_at_max_delay(self, mock_jitter):
        exc = self._make_error(litellm.RateLimitError, retry_after=3600)
        delay, is_ra = m._calculate_backoff(exc, attempt=1, max_delay=15.0)
        self.assertTrue(is_ra)
        self.assertEqual(delay, 15.0)

    @patch("random.uniform", return_value=0.15)
    def test_calculate_backoff_fallback_exponential(self, mock_jitter):
        exc = self._make_error(litellm.InternalServerError)
        delay1, is_ra1 = m._calculate_backoff(exc, attempt=1)
        delay2, is_ra2 = m._calculate_backoff(exc, attempt=2)
        delay3, is_ra3 = m._calculate_backoff(exc, attempt=3)

        self.assertFalse(is_ra1)
        self.assertEqual(delay1, 1.15)
        self.assertFalse(is_ra2)
        self.assertEqual(delay2, 2.15)
        self.assertFalse(is_ra3)
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


if __name__ == "__main__":
    unittest.main()
