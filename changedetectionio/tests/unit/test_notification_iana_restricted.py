"""
Unit tests for SSRF protection in the Apprise custom HTTP notification handler.

The handler (notification/apprise_plugin/custom_handlers.py) must block requests
to private/IANA-reserved addresses unless ALLOW_IANA_RESTRICTED_ADDRESSES=true.
"""

import pytest
from unittest.mock import patch, MagicMock


def _make_meta(url: str) -> dict:
    """Build a minimal Apprise meta dict that apprise_http_custom_handler expects."""
    from apprise.utils.parse import parse_url as apprise_parse_url
    schema = url.split("://")[0]
    parsed = apprise_parse_url(url, default_schema=schema, verify_host=False, simple=True)
    parsed["url"] = url
    parsed["schema"] = schema
    return parsed


class TestNotificationSSRFProtection:

    def test_private_ip_blocked_by_default(self):
        """Requests to private IP addresses must be blocked when ALLOW_IANA_RESTRICTED_ADDRESSES is unset."""
        from changedetectionio.notification.apprise_plugin.custom_handlers import apprise_http_custom_handler

        meta = _make_meta("post://192.168.1.100/webhook")

        with patch("changedetectionio.notification.apprise_plugin.custom_handlers.is_private_hostname", return_value=True), \
             patch.dict("os.environ", {}, clear=False):
            # Remove the env var if present so the default 'false' applies
            import os
            os.environ.pop("ALLOW_IANA_RESTRICTED_ADDRESSES", None)

            with pytest.raises(ValueError, match="ALLOW_IANA_RESTRICTED_ADDRESSES"):
                apprise_http_custom_handler(
                    body="test body",
                    title="test title",
                    notify_type="info",
                    meta=meta,
                )

    def test_loopback_blocked_by_default(self):
        """Requests to loopback addresses (127.x.x.x) must be blocked."""
        from changedetectionio.notification.apprise_plugin.custom_handlers import apprise_http_custom_handler

        meta = _make_meta("post://127.0.0.1:8080/internal")

        with patch("changedetectionio.notification.apprise_plugin.custom_handlers.is_private_hostname", return_value=True):
            import os
            os.environ.pop("ALLOW_IANA_RESTRICTED_ADDRESSES", None)

            with pytest.raises(ValueError, match="ALLOW_IANA_RESTRICTED_ADDRESSES"):
                apprise_http_custom_handler(
                    body="test body",
                    title="test title",
                    notify_type="info",
                    meta=meta,
                )

    def test_private_ip_allowed_when_env_var_set(self):
        """When ALLOW_IANA_RESTRICTED_ADDRESSES=true, requests to private IPs must go through."""
        from changedetectionio.notification.apprise_plugin.custom_handlers import apprise_http_custom_handler

        meta = _make_meta("post://192.168.1.100/webhook")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("changedetectionio.notification.apprise_plugin.custom_handlers.is_private_hostname", return_value=True), \
             patch("changedetectionio.notification.apprise_plugin.custom_handlers.requests.request", return_value=mock_response) as mock_req, \
             patch.dict("os.environ", {"ALLOW_IANA_RESTRICTED_ADDRESSES": "true"}):

            result = apprise_http_custom_handler(
                body="test body",
                title="test title",
                notify_type="info",
                meta=meta,
            )

        assert result is True
        mock_req.assert_called_once()

    def test_public_hostname_not_blocked(self):
        """Public hostnames must not be blocked by the SSRF guard."""
        from changedetectionio.notification.apprise_plugin.custom_handlers import apprise_http_custom_handler

        meta = _make_meta("post://example.com/webhook")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("changedetectionio.notification.apprise_plugin.custom_handlers.is_private_hostname", return_value=False), \
             patch("changedetectionio.notification.apprise_plugin.custom_handlers.requests.request", return_value=mock_response) as mock_req:
            import os
            os.environ.pop("ALLOW_IANA_RESTRICTED_ADDRESSES", None)

            result = apprise_http_custom_handler(
                body="test body",
                title="test title",
                notify_type="info",
                meta=meta,
            )

        assert result is True
        mock_req.assert_called_once()

    def test_error_message_contains_env_var_hint(self):
        """The ValueError message must include the ALLOW_IANA_RESTRICTED_ADDRESSES hint."""
        from changedetectionio.notification.apprise_plugin.custom_handlers import apprise_http_custom_handler

        meta = _make_meta("post://10.0.0.1/api")

        with patch("changedetectionio.notification.apprise_plugin.custom_handlers.is_private_hostname", return_value=True):
            import os
            os.environ.pop("ALLOW_IANA_RESTRICTED_ADDRESSES", None)

            with pytest.raises(ValueError) as exc_info:
                apprise_http_custom_handler(
                    body="test",
                    title="test",
                    notify_type="info",
                    meta=meta,
                )

            assert "ALLOW_IANA_RESTRICTED_ADDRESSES=true" in str(exc_info.value)
