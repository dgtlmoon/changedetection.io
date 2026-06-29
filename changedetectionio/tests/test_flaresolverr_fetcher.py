"""Unit tests for the FlareSolverr / Byparr content fetcher.

These tests stub the HTTP layer with `responses` so we don't depend on a
running FlareSolverr instance. They cover:

- success path: solution.response surfaces as self.content, status from upstream
- POST passthrough (cmd=request.post + postData)
- proxy_override propagates as FlareSolverr `proxy.url`
- FLARESOLVERR_URL env var honored, custom_browser_connection_url overrides it
- empty body raises EmptyReply (unless empty_pages_are_a_change=True)
- non-200 upstream raises Non200ErrorCodeReceived
- FlareSolverr-level failure ({"status": "error"}) raises BrowserConnectError
- network timeout raises BrowserFetchTimedOut
"""
import asyncio
import os
from unittest import mock

import pytest
import responses

from changedetectionio.content_fetchers import flaresolverr
from changedetectionio.content_fetchers.exceptions import (
    BrowserConnectError,
    BrowserFetchTimedOut,
    EmptyReply,
    Non200ErrorCodeReceived,
)


FLARESOLVERR_URL = "http://flaresolverr.test:8191/v1"


def _ok_payload(html="<html><body>hi</body></html>", status=200, headers=None):
    return {
        "status": "ok",
        "message": "Challenge solved!",
        "solution": {
            "url": "https://target.example.com/",
            "status": status,
            "response": html,
            "headers": headers or {"content-type": "text/html"},
            "userAgent": "Mozilla/5.0 ...",
            "cookies": [],
        },
    }


def _run(fetcher, **kwargs):
    asyncio.run(fetcher.run(**kwargs))


@responses.activate
def test_success_get_returns_html():
    responses.add(responses.POST, FLARESOLVERR_URL, json=_ok_payload(), status=200)
    f = flaresolverr.fetcher(custom_browser_connection_url=FLARESOLVERR_URL)
    _run(f, url="https://target.example.com/", timeout=30,
         request_method="GET", request_headers={}, request_body=None)
    assert f.status_code == 200
    assert f.content == "<html><body>hi</body></html>"
    assert f.headers["content-type"] == "text/html"
    assert f.raw_content == b"<html><body>hi</body></html>"

    # The outgoing request used cmd=request.get and propagated maxTimeout in ms
    sent = responses.calls[0].request
    import json as _json
    body = _json.loads(sent.body)
    assert body["cmd"] == "request.get"
    assert body["url"] == "https://target.example.com/"
    assert body["maxTimeout"] == 30 * 1000


@responses.activate
def test_post_passthrough_uses_request_post():
    responses.add(responses.POST, FLARESOLVERR_URL, json=_ok_payload(html="ok"), status=200)
    f = flaresolverr.fetcher(custom_browser_connection_url=FLARESOLVERR_URL)
    _run(f, url="https://target.example.com/login", timeout=10,
         request_method="POST", request_headers={"X-K": "v"},
         request_body="user=a&pass=b")
    import json as _json
    sent = _json.loads(responses.calls[0].request.body)
    assert sent["cmd"] == "request.post"
    assert sent["postData"] == "user=a&pass=b"


@responses.activate
def test_proxy_override_propagated():
    responses.add(responses.POST, FLARESOLVERR_URL, json=_ok_payload(html="x"), status=200)
    f = flaresolverr.fetcher(
        custom_browser_connection_url=FLARESOLVERR_URL,
        proxy_override="http://user:pass@proxy.test:8080",
    )
    _run(f, url="https://target.example.com/", timeout=5,
         request_method="GET", request_headers={}, request_body=None)
    import json as _json
    sent = _json.loads(responses.calls[0].request.body)
    assert sent["proxy"] == {"url": "http://user:pass@proxy.test:8080"}


def test_env_var_default_endpoint():
    with mock.patch.dict(os.environ, {"FLARESOLVERR_URL": "http://from-env:8191/v1"}, clear=False):
        f = flaresolverr.fetcher()
    assert f.browser_connection_url == "http://from-env:8191/v1"
    assert f.browser_connection_is_custom is None


def test_custom_url_overrides_env():
    with mock.patch.dict(os.environ, {"FLARESOLVERR_URL": "http://from-env:8191/v1"}, clear=False):
        f = flaresolverr.fetcher(custom_browser_connection_url="http://watch-specific:8191/v1")
    assert f.browser_connection_url == "http://watch-specific:8191/v1"
    assert f.browser_connection_is_custom is True


@responses.activate
def test_empty_body_raises_empty_reply():
    responses.add(responses.POST, FLARESOLVERR_URL, json=_ok_payload(html=""), status=200)
    f = flaresolverr.fetcher(custom_browser_connection_url=FLARESOLVERR_URL)
    with pytest.raises(EmptyReply):
        _run(f, url="https://target.example.com/", timeout=5,
             request_method="GET", request_headers={}, request_body=None)


@responses.activate
def test_empty_body_accepted_when_flag_set():
    responses.add(responses.POST, FLARESOLVERR_URL, json=_ok_payload(html=""), status=200)
    f = flaresolverr.fetcher(custom_browser_connection_url=FLARESOLVERR_URL)
    _run(f, url="https://target.example.com/", timeout=5,
         request_method="GET", request_headers={}, request_body=None,
         empty_pages_are_a_change=True)
    assert f.content == ""
    assert f.status_code == 200


@responses.activate
def test_non_200_upstream_raises():
    responses.add(responses.POST, FLARESOLVERR_URL,
                  json=_ok_payload(html="<h1>nope</h1>", status=404), status=200)
    f = flaresolverr.fetcher(custom_browser_connection_url=FLARESOLVERR_URL)
    with pytest.raises(Non200ErrorCodeReceived) as exc:
        _run(f, url="https://target.example.com/", timeout=5,
             request_method="GET", request_headers={}, request_body=None)
    assert exc.value.status_code == 404


@responses.activate
def test_non_200_upstream_swallowed_when_ignored():
    responses.add(responses.POST, FLARESOLVERR_URL,
                  json=_ok_payload(html="<h1>nope</h1>", status=404), status=200)
    f = flaresolverr.fetcher(custom_browser_connection_url=FLARESOLVERR_URL)
    _run(f, url="https://target.example.com/", timeout=5,
         request_method="GET", request_headers={}, request_body=None,
         ignore_status_codes=True)
    assert f.status_code == 404
    assert f.content == "<h1>nope</h1>"


@responses.activate
def test_flaresolverr_error_response_raises():
    responses.add(responses.POST, FLARESOLVERR_URL,
                  json={"status": "error", "message": "Could not bypass"}, status=200)
    f = flaresolverr.fetcher(custom_browser_connection_url=FLARESOLVERR_URL)
    with pytest.raises(BrowserConnectError):
        _run(f, url="https://target.example.com/", timeout=5,
             request_method="GET", request_headers={}, request_body=None)


def test_timeout_raises_browser_fetch_timed_out():
    import requests as real_requests
    with mock.patch("requests.post", side_effect=real_requests.exceptions.Timeout("boom")):
        f = flaresolverr.fetcher(custom_browser_connection_url=FLARESOLVERR_URL)
        with pytest.raises(BrowserFetchTimedOut):
            _run(f, url="https://target.example.com/", timeout=2,
                 request_method="GET", request_headers={}, request_body=None)


def test_binary_fetch_rejected():
    f = flaresolverr.fetcher(custom_browser_connection_url=FLARESOLVERR_URL)
    with pytest.raises(BrowserConnectError):
        _run(f, url="https://target.example.com/file.pdf", timeout=5,
             request_method="GET", request_headers={}, request_body=None,
             is_binary=True)
