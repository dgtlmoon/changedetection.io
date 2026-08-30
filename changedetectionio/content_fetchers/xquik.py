import asyncio
import json
import os
import re
from urllib.parse import parse_qs, urlparse

from flask_babel import lazy_gettext as _l

from changedetectionio.content_fetchers.base import Fetcher
from changedetectionio.content_fetchers.exceptions import (
    BrowserStepsInUnsupportedFetcher,
    Non200ErrorCodeReceived,
)

XQUIK_SEARCH_URL = "https://xquik.com/api/v1/x/tweets/search"
XQUIK_RESULT_LIMIT = 25
X_SEARCH_HOSTS = {"twitter.com", "www.twitter.com", "x.com", "www.x.com"}
X_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,15}$")


def parse_x_search_query(url):
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in X_SEARCH_HOSTS
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path.rstrip("/") != "/search"
    ):
        raise ValueError("Xquik requires an https://x.com/search?q=... watch URL.")

    values = parse_qs(parsed.query, keep_blank_values=True).get("q", [])
    if len(values) != 1 or not values[0].strip():
        raise ValueError("Xquik requires exactly one non-empty X search query.")

    return values[0].strip()


def normalize_search_results(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("tweets"), list):
        raise ValueError("Xquik returned an invalid Tweet search response.")

    results = {}
    for tweet in payload["tweets"]:
        if not isinstance(tweet, dict):
            raise ValueError("Xquik returned an invalid Tweet search result.")

        tweet_id = tweet.get("id")
        text = tweet.get("text")
        if not isinstance(tweet_id, str) or not tweet_id.isdigit() or not isinstance(text, str):
            raise ValueError("Xquik returned an invalid Tweet search result.")

        result = {
            "id": tweet_id,
            "text": text,
            "url": f"https://x.com/i/web/status/{tweet_id}",
        }
        created_at = tweet.get("createdAt")
        if isinstance(created_at, str) and created_at:
            result["createdAt"] = created_at

        author = tweet.get("author")
        if isinstance(author, dict):
            username = author.get("username")
            if isinstance(username, str) and X_USERNAME_PATTERN.fullmatch(username):
                result["author"] = {"username": username}
                result["url"] = f"https://x.com/{username}/status/{tweet_id}"

        results.setdefault(tweet_id, result)

    return [results[tweet_id] for tweet_id in sorted(results, key=int)]


class fetcher(Fetcher):  # noqa: N801 - Built-in fetchers use this public class name.
    fetcher_description = _l("Xquik X search API (metered)")
    supports_global_default = False

    def __init__(
        self,
        proxy_override=None,
        custom_browser_connection_url=None,
        session_factory=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.proxy_override = proxy_override
        self.session_factory = session_factory

    def _run_sync(self, url, timeout, request_method):
        if self.browser_steps:
            raise BrowserStepsInUnsupportedFetcher(url=url)
        if request_method != "GET":
            raise ValueError("Xquik search watches require the GET request method.")

        query = parse_x_search_query(url)
        api_key = os.getenv("XQUIK_API_KEY", "").strip()
        if not api_key:
            raise ValueError("XQUIK_API_KEY is required for the Xquik fetch method.")

        if self.session_factory is None:
            import requests

            session = requests.Session()
        else:
            session = self.session_factory()

        proxies = {}
        if self.proxy_override:
            proxies = {"http": self.proxy_override, "https": self.proxy_override}
        else:
            if self.system_http_proxy:
                proxies["http"] = self.system_http_proxy
            if self.system_https_proxy:
                proxies["https"] = self.system_https_proxy

        response = session.request(
            "GET",
            XQUIK_SEARCH_URL,
            allow_redirects=False,
            headers={"accept": "application/json", "x-api-key": api_key},
            params={"limit": XQUIK_RESULT_LIMIT, "q": query, "queryType": "Latest"},
            proxies=proxies,
            timeout=timeout,
            verify=True,
        )
        if response.status_code != 200:
            raise Non200ErrorCodeReceived(
                status_code=response.status_code,
                url=XQUIK_SEARCH_URL,
            )

        try:
            payload = response.json()
        except ValueError as error:
            raise ValueError("Xquik returned an invalid JSON response.") from error

        content = json.dumps(
            {"query": query, "tweets": normalize_search_results(payload)},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        self.content = content
        self.raw_content = content.encode("utf-8")
        self.headers = {"content-type": "application/json; charset=utf-8"}
        self.status_code = 200

    async def run(
        self,
        fetch_favicon=True,
        current_include_filters=None,
        empty_pages_are_a_change=False,
        ignore_status_codes=False,
        is_binary=False,
        request_body=None,
        request_headers=None,
        request_method=None,
        screenshot_format=None,
        timeout=None,
        url=None,
        watch_uuid=None,
    ):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._run_sync(url=url, timeout=timeout, request_method=request_method),
        )

    async def quit(self, watch=None):
        return


class XquikFetcherPlugin:
    def register_content_fetcher(self):
        return "html_xquik", fetcher


xquik_plugin = XquikFetcherPlugin()
