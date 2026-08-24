import asyncio
import json

import pytest

from changedetectionio import content_fetchers
from changedetectionio.content_fetchers.exceptions import (
    BrowserStepsInUnsupportedFetcher,
    Non200ErrorCodeReceived,
)
from changedetectionio.content_fetchers.xquik import (
    XQUIK_RESULT_LIMIT,
    XQUIK_SEARCH_URL,
    fetcher,
    normalize_search_results,
    parse_x_search_query,
)


class FakeResponse:
    def __init__(self, payload=None, status_code=200, text=""):
        self.payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeSession:
    def __init__(self, response):
        self.calls = []
        self.response = response

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.response


def run_fetch(fetcher_instance, url="https://x.com/search?q=change+detection&f=live"):
    asyncio.run(
        fetcher_instance.run(
            request_method="GET",
            timeout=12,
            url=url,
        )
    )


def test_parse_x_search_query_accepts_current_and_legacy_hosts():
    assert parse_x_search_query("https://x.com/search?q=release+notes&f=live") == "release notes"
    assert parse_x_search_query("https://twitter.com/search/?q=%23python") == "#python"


@pytest.mark.parametrize(
    "url",
    (
        "http://x.com/search?q=test",
        "https://example.com/search?q=test",
        "https://x.com/home?q=test",
        "https://x.com/search",
        "https://x.com/search?q=",
        "https://x.com/search?q=one&q=two",
        "https://user@x.com/search?q=test",
        "https://x.com:443/search?q=test",
    ),
)
def test_parse_x_search_query_rejects_ambiguous_or_unsafe_urls(url):
    with pytest.raises(ValueError):
        parse_x_search_query(url)


def test_normalize_search_results_removes_volatile_fields_and_sorts_ids():
    payload = {
        "tweets": [
            {
                "id": "20",
                "text": "Second",
                "createdAt": "2026-08-24T12:00:00Z",
                "likeCount": 99,
                "author": {"username": "valid_user", "followers": 1000},
            },
            {"id": "10", "text": "First", "replyCount": 50},
            {"id": "20", "text": "Second duplicate", "retweetCount": 12},
        ]
    }

    assert normalize_search_results(payload) == [
        {
            "id": "10",
            "text": "First",
            "url": "https://x.com/i/web/status/10",
        },
        {
            "author": {"username": "valid_user"},
            "createdAt": "2026-08-24T12:00:00Z",
            "id": "20",
            "text": "Second",
            "url": "https://x.com/valid_user/status/20",
        },
    ]


@pytest.mark.parametrize(
    "tweet",
    (None, {"id": "not-numeric", "text": "Invalid"}, {"id": "30"}),
)
def test_normalize_search_results_rejects_invalid_tweets(tweet):
    with pytest.raises(ValueError, match="invalid Tweet search result"):
        normalize_search_results({"tweets": [tweet]})


def test_xquik_fetcher_uses_fixed_endpoint_and_server_key(monkeypatch):
    response = FakeResponse(
        {
            "tweets": [
                {
                    "id": "42",
                    "text": "A useful release",
                    "createdAt": "2026-08-24T12:00:00Z",
                    "viewCount": 500,
                    "author": {"username": "release_bot", "name": "Release bot"},
                }
            ],
            "next_cursor": "private-pagination-state",
        }
    )
    session = FakeSession(response)
    monkeypatch.setenv("XQUIK_API_KEY", "test-key")
    fetcher_instance = fetcher(session_factory=lambda: session)
    fetcher_instance.system_http_proxy = None
    fetcher_instance.system_https_proxy = None

    run_fetch(fetcher_instance)

    assert session.calls == [
        (
            "GET",
            XQUIK_SEARCH_URL,
            {
                "allow_redirects": False,
                "headers": {"accept": "application/json", "x-api-key": "test-key"},
                "params": {
                    "limit": XQUIK_RESULT_LIMIT,
                    "q": "change detection",
                    "queryType": "Latest",
                },
                "proxies": {},
                "timeout": 12,
                "verify": True,
            },
        )
    ]
    assert json.loads(fetcher_instance.content) == {
        "query": "change detection",
        "tweets": [
            {
                "author": {"username": "release_bot"},
                "createdAt": "2026-08-24T12:00:00Z",
                "id": "42",
                "text": "A useful release",
                "url": "https://x.com/release_bot/status/42",
            }
        ],
    }
    assert fetcher_instance.raw_content == fetcher_instance.content.encode("utf-8")
    assert fetcher_instance.get_all_headers() == {"content-type": "application/json; charset=utf-8"}
    assert fetcher_instance.status_code == 200
    assert "viewCount" not in fetcher_instance.content
    assert "next_cursor" not in fetcher_instance.content


def test_xquik_fetcher_requires_key_before_network(monkeypatch):
    session = FakeSession(FakeResponse({"tweets": []}))
    monkeypatch.delenv("XQUIK_API_KEY", raising=False)

    with pytest.raises(ValueError, match="XQUIK_API_KEY is required"):
        run_fetch(fetcher(session_factory=lambda: session))

    assert session.calls == []


def test_xquik_fetcher_rejects_browser_steps(monkeypatch):
    monkeypatch.setenv("XQUIK_API_KEY", "test-key")
    fetcher_instance = fetcher(session_factory=lambda: FakeSession(FakeResponse({"tweets": []})))
    fetcher_instance.browser_steps = [{"operation": "click"}]

    with pytest.raises(BrowserStepsInUnsupportedFetcher):
        run_fetch(fetcher_instance)


def test_xquik_fetcher_preserves_http_failure(monkeypatch):
    monkeypatch.setenv("XQUIK_API_KEY", "test-key")
    response = FakeResponse(status_code=429, text='{"error":"rate limited"}')

    with pytest.raises(Non200ErrorCodeReceived) as caught:
        run_fetch(fetcher(session_factory=lambda: FakeSession(response)))

    assert caught.value.status_code == 429
    assert caught.value.url == XQUIK_SEARCH_URL


def test_xquik_fetcher_rejects_invalid_json(monkeypatch):
    monkeypatch.setenv("XQUIK_API_KEY", "test-key")
    response = FakeResponse(payload=ValueError("bad json"))

    with pytest.raises(ValueError, match="invalid JSON"):
        run_fetch(fetcher(session_factory=lambda: FakeSession(response)))


def test_xquik_fetcher_is_watch_only():
    watch_fetchers = {name for name, _description in content_fetchers.available_fetchers()}
    global_fetchers = {
        name for name, _description in content_fetchers.available_fetchers(include_watch_only=False)
    }

    assert "html_xquik" in watch_fetchers
    assert "html_xquik" not in global_fetchers
