import json
from unittest.mock import patch

import apprise
import pytest
import requests
from apprise.utils.parse import parse_url as apprise_parse_url

from changedetectionio.notification.apprise_plugin.custom_handlers import (
    _get_auth,
    _get_headers,
    _get_params,
    apprise_http_custom_handler,
    SUPPORTED_HTTP_METHODS,
)


@pytest.mark.parametrize(
    "url,expected_auth",
    [
        ("get://user:pass@localhost:9999", ("user", "pass")),
        # A username without a password is not a login
        ("get://user@localhost:9999", ""),
        # Query parameters are for the remote endpoint, never credentials
        ("get://localhost:9999?user=abc&token=xyz", ""),
        ("get://localhost:9999?user=abc&password=xyz", ""),
        ("get://localhost:9999?user=abc&pass=xyz", ""),
        ("get://localhost:9999", ""),
        ("get://user%20name:pass%20word@localhost:9999", ("user name", "pass word")),
    ],
)
def test_get_auth(url, expected_auth):
    """Test authentication extraction with various URL formats."""
    parsed_url = apprise_parse_url(url)
    assert _get_auth(parsed_url) == expected_auth


@pytest.mark.parametrize(
    "url,body,expected_content_type",
    [
        (
            "get://localhost:9999?+content-type=application/xml",
            "test",
            "application/xml",
        ),
        ("get://localhost:9999", '{"key": "value"}', "application/json; charset=utf-8"),
        ("get://localhost:9999", "plain text", None),
        ("get://localhost:9999?+content-type=text/plain", "test", "text/plain"),
    ],
)
def test_get_headers(url, body, expected_content_type):
    """Test header extraction and content type detection."""
    parsed_url = apprise_parse_url(url)
    headers = _get_headers(parsed_url, body)

    if expected_content_type:
        assert headers.get("Content-Type") == expected_content_type


@pytest.mark.parametrize(
    "url,expected_params",
    [
        ("get://localhost:9999?param1=value1", {"param1": "value1"}),
        ("get://localhost:9999?param1=value1&-param2=ignored", {"param1": "value1"}),
        ("get://localhost:9999?param1=value1&+header=test", {"param1": "value1"}),
        # Capitalised header and ignore names are never sent as query parameters too
        ("get://localhost:9999?param1=value1&+X-Key=secret", {"param1": "value1"}),
        ("get://localhost:9999?param1=value1&+Authorization=Bearer%20token", {"param1": "value1"}),
        ("get://localhost:9999?param1=value1&-Param2=ignored", {"param1": "value1"}),
        ("get://localhost:9999?user=abc&token=xyz", {"user": "abc", "token": "xyz"}),
        (
            "get://localhost:9999?encoded%20param=encoded%20value",
            {"encoded param": "encoded value"},
        ),
    ],
)
def test_get_params(url, expected_params):
    """Test parameter extraction with URL encoding and exclusion logic."""
    parsed_url = apprise_parse_url(url)
    params = _get_params(parsed_url)
    assert dict(params) == expected_params


@pytest.mark.parametrize(
    "url,schema,method",
    [
        ("get://localhost:9999", "get", "GET"),
        ("post://localhost:9999", "post", "POST"),
        ("delete://localhost:9999", "delete", "DELETE"),
    ],
)
@patch("requests.request")
def test_apprise_custom_api_call_success(mock_request, url, schema, method):
    """Test successful API calls with different HTTP methods and schemas."""
    mock_request.return_value.raise_for_status.return_value = None

    meta = {"url": url, "schema": schema}
    result = apprise_http_custom_handler(
        body="test body", title="Test Title", notify_type="info", meta=meta
    )

    assert result is True
    mock_request.assert_called_once()

    call_args = mock_request.call_args
    assert call_args[1]["method"] == method.upper()
    assert call_args[1]["url"].startswith("http")


@patch("requests.request")
def test_apprise_custom_api_call_with_auth(mock_request):
    """Test API call with authentication."""
    mock_request.return_value.raise_for_status.return_value = None

    url = "get://user:pass@localhost:9999/secure"
    meta = {"url": url, "schema": "get"}

    result = apprise_http_custom_handler(
        body=json.dumps({"key": "value"}),
        title="Secure Test",
        notify_type="info",
        meta=meta,
    )

    assert result is True
    mock_request.assert_called_once()
    call_args = mock_request.call_args
    assert call_args[1]["auth"] == ("user", "pass")


@pytest.mark.parametrize(
    "exception_type",
    [requests.RequestException, requests.HTTPError, Exception],
)
@patch("requests.request")
def test_apprise_custom_api_call_failure(mock_request, exception_type):
    """A failed request raises out of the handler, and is reported as a failed send by Apprise."""
    url = "get://localhost:9999/error"
    mock_request.side_effect = exception_type("Error occurred")

    with pytest.raises(exception_type):
        apprise_http_custom_handler(
            body="error body", title="Error Test", notify_type="error", meta={"url": url, "schema": "get"}
        )

    apobj = apprise.Apprise()
    assert apobj.add(url)
    assert not apobj.notify(body="error body", title="Error Test")


@patch("requests.request")
def test_invalid_url_parsing(mock_request):
    """A URL that cannot be parsed is a failed send, nothing is requested."""
    result = apprise_http_custom_handler(
        body="test", title="Invalid URL", notify_type="info", meta={"url": "get://", "schema": "get"}
    )

    assert result is False
    mock_request.assert_not_called()


@pytest.mark.parametrize(
    "schema,expected_method",
    [
        (http_method, http_method.upper())
        for http_method in SUPPORTED_HTTP_METHODS
    ],
)
@patch("requests.request")
def test_http_methods(mock_request, schema, expected_method):
    """Test all supported HTTP methods."""
    mock_request.return_value.raise_for_status.return_value = None

    url = f"{schema}://localhost:9999"

    result = apprise_http_custom_handler(
        body="test body",
        title="Test Title",
        notify_type="info",
        meta={"url": url, "schema": schema},
    )

    assert result is True
    mock_request.assert_called_once()

    call_args = mock_request.call_args
    assert call_args[1]["method"] == expected_method


@pytest.mark.parametrize(
    "input_schema,expected_method",
    [
        (f"{http_method}s", http_method.upper())
        for http_method in SUPPORTED_HTTP_METHODS
    ],
)
@patch("requests.request")
def test_https_method_conversion(
    mock_request, input_schema, expected_method
):
    """Validate that methods ending with 's' use HTTPS and correct HTTP method."""
    mock_request.return_value.raise_for_status.return_value = None

    url = f"{input_schema}://localhost:9999"

    result = apprise_http_custom_handler(
        body="test body",
        title="Test Title",
        notify_type="info",
        meta={"url": url, "schema": input_schema},
    )

    assert result is True
    mock_request.assert_called_once()

    call_args = mock_request.call_args

    assert call_args[1]["method"] == expected_method
    assert call_args[1]["url"].startswith("https")


@pytest.mark.parametrize("schema", sorted(SUPPORTED_HTTP_METHODS))
@pytest.mark.parametrize(
    "query,expected_params",
    [
        ("user=abc&token=xyz&title=hello", {"user": "abc", "token": "xyz", "title": "hello"}),
        ("user=abc", {"user": "abc"}),
        ("user=abc&password=secret", {"user": "abc", "password": "secret"}),
        ("user=abc&pass=secret", {"user": "abc", "pass": "secret"}),
        ("verify=no&retry=2", {"verify": "no", "retry": "2"}),
    ],
)
@patch("requests.request")
def test_query_params_reach_endpoint_untouched(mock_request, schema, query, expected_params):
    """Sent through Apprise itself: ?user=, ?pass= etc are plain query parameters for the remote
    endpoint, they are never turned into a login and never moved into the URL."""
    mock_request.return_value.raise_for_status.return_value = None

    apobj = apprise.Apprise()
    assert apobj.add(f"{schema}://localhost:9999/webhook?{query}")
    assert apobj.notify(body="test body", title="Test Title")

    mock_request.assert_called_once()
    call_args = mock_request.call_args[1]
    assert call_args["method"] == schema.upper()
    assert call_args["url"] == "http://localhost:9999/webhook"
    assert call_args["auth"] == ""
    assert dict(call_args["params"]) == expected_params


@patch("requests.request")
def test_url_credentials_still_used_with_user_query_param(mock_request):
    """user:pass@ in the URL is the login, a ?user= beside it is still just a query parameter."""
    mock_request.return_value.raise_for_status.return_value = None

    apobj = apprise.Apprise()
    assert apobj.add("post://login:secret@localhost:9999/webhook?user=abc")
    assert apobj.notify(body="test body", title="Test Title")

    call_args = mock_request.call_args[1]
    assert call_args["auth"] == ("login", "secret")
    assert dict(call_args["params"]) == {"user": "abc"}
