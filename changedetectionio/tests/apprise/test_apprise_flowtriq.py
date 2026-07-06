import json
import os
from unittest.mock import patch, MagicMock

import pytest
import requests

from changedetectionio.notification.apprise_plugin.flowtriq import NotifyFlowtriq


def test_flowtriq_parse_url_basic():
    """Test basic URL parsing without API key."""
    result = NotifyFlowtriq.parse_url(
        'flowtriq://app.flowtriq.com/api/v1/webhooks/changedetection'
    )
    assert result is not None
    assert result['host'] == 'app.flowtriq.com'
    assert result['apikey'] is None


def test_flowtriq_parse_url_with_apikey():
    """Test URL parsing with API key."""
    result = NotifyFlowtriq.parse_url(
        'flowtriq://app.flowtriq.com/api/v1/webhooks/changedetection?key=test-key-123'
    )
    assert result is not None
    assert result['host'] == 'app.flowtriq.com'
    assert result['apikey'] == 'test-key-123'


@patch("requests.post")
def test_flowtriq_send_success(mock_post):
    """Test successful notification send."""
    mock_post.return_value = MagicMock(status_code=200)
    mock_post.return_value.raise_for_status.return_value = None

    plugin = NotifyFlowtriq(
        host='app.flowtriq.com',
        fullpath='/api/v1/webhooks/changedetection',
        apikey='test-key',
    )

    result = plugin.send(body='Page changed', title='https://example.com')

    assert result is True
    mock_post.assert_called_once()

    call_args = mock_post.call_args
    assert call_args[0][0] == 'https://app.flowtriq.com/api/v1/webhooks/changedetection'

    headers = call_args[1]['headers']
    assert headers['Content-Type'] == 'application/json'
    assert headers['X-API-Key'] == 'test-key'

    payload = json.loads(call_args[1]['data'])
    assert payload['source'] == 'changedetection'
    assert payload['status'] == 'change_detected'
    assert payload['body'] == 'Page changed'


@patch("requests.post")
def test_flowtriq_send_without_apikey(mock_post):
    """Test notification send without API key (no X-API-Key header)."""
    mock_post.return_value = MagicMock(status_code=200)
    mock_post.return_value.raise_for_status.return_value = None

    plugin = NotifyFlowtriq(
        host='app.flowtriq.com',
        fullpath='/api/v1/webhooks/changedetection',
    )

    result = plugin.send(body='Page changed', title='https://example.com')

    assert result is True
    headers = mock_post.call_args[1]['headers']
    assert 'X-API-Key' not in headers


@patch("requests.post")
def test_flowtriq_send_failure(mock_post):
    """Test notification failure handling."""
    mock_post.side_effect = requests.RequestException("Connection refused")

    plugin = NotifyFlowtriq(
        host='app.flowtriq.com',
        fullpath='/api/v1/webhooks/changedetection',
    )

    result = plugin.send(body='Page changed', title='https://example.com')

    assert result is False


@patch("requests.post")
def test_flowtriq_payload_structure(mock_post):
    """Test the JSON payload structure matches what Flowtriq expects."""
    mock_post.return_value = MagicMock(status_code=200)
    mock_post.return_value.raise_for_status.return_value = None

    plugin = NotifyFlowtriq(
        host='app.flowtriq.com',
        fullpath='/api/v1/webhooks/changedetection',
        apikey='my-key',
    )

    plugin.send(
        body='Line removed: old content\nLine added: new content',
        title='https://monitored-site.com/status',
    )

    payload = json.loads(mock_post.call_args[1]['data'])
    assert payload == {
        'source': 'changedetection',
        'title': 'https://monitored-site.com/status',
        'body': 'Line removed: old content\nLine added: new content',
        'status': 'change_detected',
    }


def test_flowtriq_ssrf_blocks_private_address():
    """Test that SSRF protection blocks private/loopback addresses."""
    plugin = NotifyFlowtriq(
        host='localhost',
        fullpath='/api/v1/webhooks/changedetection',
    )

    # Ensure ALLOW_IANA_RESTRICTED_ADDRESSES is not set
    with patch.dict(os.environ, {}, clear=True):
        result = plugin.send(body='Page changed', title='test')

    assert result is False


@patch("requests.post")
def test_flowtriq_url_without_apikey(mock_post):
    """Test url() does not leave trailing ?key= when no API key is set."""
    plugin = NotifyFlowtriq(
        host='app.flowtriq.com',
        fullpath='/api/v1/webhooks/changedetection',
    )

    url = plugin.url()
    assert url == 'flowtriq://app.flowtriq.com/api/v1/webhooks/changedetection'
    assert '?key=' not in url
