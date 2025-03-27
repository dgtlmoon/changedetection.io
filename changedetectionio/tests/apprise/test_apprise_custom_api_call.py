import json
from unittest.mock import patch

import pytest
import requests
from apprise.utils.parse import parse_url as apprise_parse_url

from ...apprise_plugin.custom_handlers import (
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
        ("get://user@localhost:9999", "user"),
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
    "exception_type,expected_result",
    [
        (requests.RequestException, False),
        (requests.HTTPError, False),
        (Exception, False),
    ],
)
@patch("requests.request")
def test_apprise_custom_api_call_failure(mock_request, exception_type, expected_result):
    """Test various failure scenarios."""
    url = "get://localhost:9999/error"
    meta = {"url": url, "schema": "get"}

    # Simulate different types of exceptions
    mock_request.side_effect = exception_type("Error occurred")

    result = apprise_http_custom_handler(
        body="error body", title="Error Test", notify_type="error", meta=meta
    )

    assert result == expected_result


def test_invalid_url_parsing():
    """Test handling of invalid URL parsing."""
    meta = {"url": "invalid://url", "schema": "invalid"}
    result = apprise_http_custom_handler(
        body="test", title="Invalid URL", notify_type="info", meta=meta
    )

    assert result is False


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
