from __future__ import annotations

import unittest
from email.message import Message
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.request import Request

from github_monitor_desktop.github_api import GitHubAPIError, GitHubClient, RateLimitExceeded, SafeRedirectHandler


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.headers = Message()
        self.status = 200

    def read(self, _size=-1):
        return self.payload

    def close(self):
        pass


class GitHubAPITests(unittest.TestCase):
    def test_cross_host_redirect_strips_authorization(self):
        request = Request(
            "https://api.github.com/repos/owner/repo/zipball/v1",
            headers={"Authorization": "Bearer secret", "User-Agent": "test"},
        )
        redirected = SafeRedirectHandler().redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://codeload.github.com/owner/repo/legacy.zip/v1",
        )
        self.assertIsNotNone(redirected)
        self.assertIsNone(redirected.get_header("Authorization"))
        self.assertEqual(redirected.get_header("User-agent"), "test")

    def test_same_host_redirect_keeps_authorization(self):
        request = Request("https://api.github.com/a", headers={"Authorization": "Bearer secret"})
        redirected = SafeRedirectHandler().redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://api.github.com/b",
        )
        self.assertEqual(redirected.get_header("Authorization"), "Bearer secret")

    def test_transient_connection_failure_retries_with_backoff(self):
        calls = []
        sleeps = []

        def opener(_request, timeout):
            calls.append(timeout)
            if len(calls) < 3:
                raise URLError("temporary TLS failure")
            return FakeResponse(b'{"ok": true}')

        client = GitHubClient(opener=opener, retry_backoff=0.25, sleep=sleeps.append)
        payload, _meta = client.request_json("/test")
        self.assertEqual(payload, {"ok": True})
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [0.25, 0.5])

    def test_authenticated_user_uses_supplied_token(self):
        requests = []

        def opener(request, timeout):
            requests.append(request)
            return FakeResponse(b'{"login":"octocat"}')

        client = GitHubClient("github_pat_example", opener=opener)
        user = client.get_authenticated_user()

        self.assertEqual(user["login"], "octocat")
        self.assertEqual(requests[0].full_url, "https://api.github.com/user")
        self.assertEqual(requests[0].get_header("Authorization"), "Bearer github_pat_example")

    def test_non_transient_http_error_is_not_retried(self):
        calls = []

        def opener(request, timeout):
            calls.append(request.full_url)
            raise HTTPError(request.full_url, 404, "Not Found", Message(), BytesIO(b'{"message":"missing"}'))

        client = GitHubClient(opener=opener, sleep=lambda _seconds: None)
        with self.assertRaises(GitHubAPIError):
            client.request_json("/missing")
        self.assertEqual(len(calls), 1)

    def test_rate_limit_error_records_zero_for_the_whole_check(self):
        headers = Message()
        headers["X-RateLimit-Remaining"] = "0"
        headers["X-RateLimit-Reset"] = "123456"

        def opener(request, timeout):
            raise HTTPError(request.full_url, 403, "Forbidden", headers, BytesIO(b'{"message":"rate limit exceeded"}'))

        client = GitHubClient(opener=opener, sleep=lambda _seconds: None)
        with self.assertRaises(RateLimitExceeded):
            client.request_json("/limited")
        self.assertTrue(client.rate_limited)
        self.assertEqual(client.minimum_rate_remaining, 0)
        self.assertEqual(client.rate_reset, 123456)


if __name__ == "__main__":
    unittest.main()
