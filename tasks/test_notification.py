"""
Unit tests for the TicketWatch Slack notification module.

Tests cover:
- Slack link formatting
- Price formatting
- Alert message building
- Notification handler (mocked)
"""

import pytest
import json
from unittest.mock import patch, MagicMock
from datetime import datetime

from tasks.notification import (
    format_slack_link,
    format_price,
    format_price_range,
    TicketAlertMessage,
    SlackNotificationHandler,
    send_ticket_alert,
    format_changedetection_notification,
    ALERT_TYPES,
)


# =============================================================================
# Slack Link Formatting Tests
# =============================================================================

class TestSlackLinkFormatting:
    """Tests for Slack link markup formatting."""

    def test_format_slack_link_url_only(self):
        """Test link formatting with URL only."""
        result = format_slack_link("https://example.com")
        assert result == "<https://example.com>"

    def test_format_slack_link_with_text(self):
        """Test link formatting with display text."""
        result = format_slack_link("https://example.com", "Example")
        assert result == "<https://example.com|Example>"

    def test_format_slack_link_with_special_characters(self):
        """Test link formatting preserves special characters in URL."""
        result = format_slack_link("https://example.com/path?param=value&other=123")
        assert result == "<https://example.com/path?param=value&other=123>"

    def test_format_slack_link_with_empty_text(self):
        """Test link formatting with empty text falls back to URL only."""
        result = format_slack_link("https://example.com", "")
        assert result == "<https://example.com>"

    def test_format_slack_link_with_none_text(self):
        """Test link formatting with None text uses URL only."""
        result = format_slack_link("https://example.com", None)
        assert result == "<https://example.com>"


# =============================================================================
# Price Formatting Tests
# =============================================================================

class TestPriceFormatting:
    """Tests for price formatting functions."""

    def test_format_price_usd(self):
        """Test USD price formatting."""
        assert format_price(50.00, "USD") == "$50.00"
        assert format_price(99.99, "USD") == "$99.99"

    def test_format_price_other_currencies(self):
        """Test formatting with other currency codes."""
        assert format_price(50.00, "EUR") == "€50.00"
        assert format_price(50.00, "GBP") == "£50.00"
        assert format_price(50.00, "CAD") == "C$50.00"

    def test_format_price_unknown_currency(self):
        """Test formatting with unknown currency code."""
        result = format_price(50.00, "XYZ")
        assert "50.00" in result
        assert "XYZ" in result

    def test_format_price_integer(self):
        """Test formatting integer prices."""
        assert format_price(50, "USD") == "$50.00"

    def test_format_price_string(self):
        """Test formatting string prices."""
        result = format_price("50.00", "USD")
        assert "$50.00" in result

    def test_format_price_range_single_price(self):
        """Test price range with single price."""
        prices = [{"price": 50.00, "currency": "USD"}]
        result = format_price_range(prices)
        assert result == "$50.00"

    def test_format_price_range_multiple_prices(self):
        """Test price range with multiple prices."""
        prices = [
            {"price": 25.00, "currency": "USD"},
            {"price": 75.00, "currency": "USD"},
            {"price": 50.00, "currency": "USD"},
        ]
        result = format_price_range(prices)
        assert result == "$25.00 - $75.00"

    def test_format_price_range_empty(self):
        """Test price range with empty list."""
        result = format_price_range([])
        assert result == "Price not available"

    def test_format_price_range_with_value_key(self):
        """Test price range with 'value' key instead of 'price'."""
        prices = [{"value": 50.00, "currency": "USD"}]
        result = format_price_range(prices)
        assert result == "$50.00"


# =============================================================================
# TicketAlertMessage Builder Tests
# =============================================================================

class TestTicketAlertMessage:
    """Tests for the TicketAlertMessage builder."""

    def test_builder_chain(self):
        """Test that builder methods return self for chaining."""
        builder = TicketAlertMessage()
        result = (builder
                  .set_event("Test Event", "Test Venue")
                  .set_prices([{"price": 50}])
                  .set_url("https://example.com")
                  .set_availability("in_stock")
                  .set_change_type("new")
                  .add_info("Key", "Value"))
        assert result is builder

    def test_build_text_includes_event_name(self):
        """Test that text output includes event name."""
        builder = TicketAlertMessage()
        builder.set_event("Concert Name")
        text = builder.build_text()
        assert "Concert Name" in text

    def test_build_text_includes_venue(self):
        """Test that text output includes venue."""
        builder = TicketAlertMessage()
        builder.set_event("Event", "The Venue")
        text = builder.build_text()
        assert "The Venue" in text

    def test_build_text_includes_prices(self):
        """Test that text output includes prices."""
        builder = TicketAlertMessage()
        builder.set_prices([{"price": 50.00, "currency": "USD"}])
        text = builder.build_text()
        assert "$50.00" in text

    def test_build_text_includes_url_as_link(self):
        """Test that text output includes URL as Slack link."""
        builder = TicketAlertMessage()
        builder.set_url("https://tickets.example.com")
        text = builder.build_text()
        assert "<https://tickets.example.com|View Tickets>" in text

    def test_build_text_includes_availability(self):
        """Test that text output includes availability status."""
        builder = TicketAlertMessage()
        builder.set_availability("in_stock")
        text = builder.build_text()
        assert "Available" in text

    def test_build_text_sold_out_availability(self):
        """Test sold out availability status."""
        builder = TicketAlertMessage()
        builder.set_availability("out_of_stock")
        text = builder.build_text()
        assert "Sold Out" in text

    def test_build_text_with_change_type(self):
        """Test different change types produce correct headers."""
        for change_type, config in ALERT_TYPES.items():
            builder = TicketAlertMessage()
            builder.set_change_type(change_type)
            text = builder.build_text()
            assert config.header in text
            assert config.emoji in text

    def test_build_text_with_additional_info(self):
        """Test that additional info is included."""
        builder = TicketAlertMessage()
        builder.add_info("Date", "2025-03-15")
        builder.add_info("Age", "21+")
        text = builder.build_text()
        assert "Date" in text
        assert "2025-03-15" in text
        assert "Age" in text
        assert "21+" in text

    def test_build_text_has_separators(self):
        """Test that text output has visual separators."""
        builder = TicketAlertMessage()
        builder.set_event("Event")
        text = builder.build_text()
        # Check for separator characters (using ━ as defined)
        assert "━" in text or "-" in text

    def test_build_text_has_emojis(self):
        """Test that text output has emojis."""
        builder = TicketAlertMessage()
        builder.set_event("Event", "Venue")
        builder.set_change_type("new")
        text = builder.build_text()
        # Check for emoji shortcodes
        assert ":" in text  # Emoji shortcodes contain colons

    def test_build_text_includes_timestamp(self):
        """Test that text output includes timestamp."""
        builder = TicketAlertMessage()
        text = builder.build_text()
        assert "TicketWatch" in text
        # Should have a date-like pattern
        assert datetime.now().strftime('%Y') in text

    def test_build_blocks_returns_list(self):
        """Test that build_blocks returns a list."""
        builder = TicketAlertMessage()
        builder.set_event("Event")
        blocks = builder.build_blocks()
        assert isinstance(blocks, list)

    def test_build_blocks_has_header(self):
        """Test that blocks include a header block."""
        builder = TicketAlertMessage()
        builder.set_event("Event Name")
        blocks = builder.build_blocks()

        header_blocks = [b for b in blocks if b.get("type") == "header"]
        assert len(header_blocks) >= 1

    def test_build_blocks_has_dividers(self):
        """Test that blocks include divider blocks."""
        builder = TicketAlertMessage()
        builder.set_event("Event", "Venue")
        builder.set_url("https://example.com")
        blocks = builder.build_blocks()

        divider_blocks = [b for b in blocks if b.get("type") == "divider"]
        assert len(divider_blocks) >= 1

    def test_build_blocks_has_action_button(self):
        """Test that blocks include action button when URL is set."""
        builder = TicketAlertMessage()
        builder.set_url("https://tickets.example.com")
        blocks = builder.build_blocks()

        action_blocks = [b for b in blocks if b.get("type") == "actions"]
        assert len(action_blocks) == 1
        assert action_blocks[0]["elements"][0]["url"] == "https://tickets.example.com"

    def test_build_blocks_has_context_footer(self):
        """Test that blocks include context footer."""
        builder = TicketAlertMessage()
        blocks = builder.build_blocks()

        context_blocks = [b for b in blocks if b.get("type") == "context"]
        assert len(context_blocks) >= 1

    def test_build_attachment_has_color(self):
        """Test that attachment has correct color."""
        builder = TicketAlertMessage()
        builder.set_change_type("new")
        attachment = builder.build_attachment()

        assert "color" in attachment
        assert attachment["color"] == ALERT_TYPES["new"].color

    def test_price_change_shows_old_and_new(self):
        """Test that price changes show both old and new prices."""
        builder = TicketAlertMessage()
        builder.set_prices(
            [{"price": 60.00, "currency": "USD"}],
            [{"price": 50.00, "currency": "USD"}]
        )
        builder.set_change_type("price_change")
        text = builder.build_text()

        # Should show strikethrough of old price and new price
        assert "50.00" in text
        assert "60.00" in text


# =============================================================================
# SlackNotificationHandler Tests
# =============================================================================

class TestSlackNotificationHandler:
    """Tests for the SlackNotificationHandler class."""

    def test_handler_initialization_with_url(self):
        """Test handler initializes with provided webhook URL."""
        handler = SlackNotificationHandler(webhook_url="https://hooks.slack.com/test")
        assert handler.webhook_url == "https://hooks.slack.com/test"

    def test_handler_initialization_from_env(self):
        """Test handler reads webhook URL from environment."""
        with patch.dict('os.environ', {'SLACK_WEBHOOK_URL': 'https://hooks.slack.com/env'}):
            handler = SlackNotificationHandler()
            assert handler.webhook_url == "https://hooks.slack.com/env"

    def test_handler_without_webhook_logs_warning(self):
        """Test handler logs warning when no webhook URL."""
        with patch.dict('os.environ', {}, clear=True):
            with patch('tasks.notification.logger') as mock_logger:
                handler = SlackNotificationHandler(webhook_url=None)
                # Should have logged a warning
                mock_logger.warning.assert_called()

    @patch('notification.requests.post')
    def test_send_ticket_alert_success(self, mock_post):
        """Test successful notification sending."""
        mock_post.return_value = MagicMock(status_code=200)

        handler = SlackNotificationHandler(webhook_url="https://hooks.slack.com/test")
        result = handler.send_ticket_alert(
            event_name="Test Event",
            venue="Test Venue",
            prices=[{"price": 50}],
            url="https://example.com",
            availability="in_stock",
            change_type="new"
        )

        assert result is True
        mock_post.assert_called_once()

    @patch('notification.requests.post')
    def test_send_ticket_alert_failure(self, mock_post):
        """Test notification sending failure handling."""
        mock_post.return_value = MagicMock(status_code=500, text="Error")

        handler = SlackNotificationHandler(webhook_url="https://hooks.slack.com/test")
        result = handler.send_ticket_alert(event_name="Test Event")

        assert result is False

    @patch('notification.requests.post')
    def test_send_ticket_alert_timeout(self, mock_post):
        """Test notification timeout handling."""
        import requests
        mock_post.side_effect = requests.exceptions.Timeout()

        handler = SlackNotificationHandler(webhook_url="https://hooks.slack.com/test")
        result = handler.send_ticket_alert(event_name="Test Event")

        assert result is False

    def test_send_without_webhook_returns_false(self):
        """Test sending without webhook URL returns False."""
        with patch.dict('os.environ', {}, clear=True):
            handler = SlackNotificationHandler(webhook_url=None)
            result = handler.send_ticket_alert(event_name="Test")
            assert result is False

    @patch('notification.requests.post')
    def test_send_raw_message(self, mock_post):
        """Test sending raw message."""
        mock_post.return_value = MagicMock(status_code=200)

        handler = SlackNotificationHandler(webhook_url="https://hooks.slack.com/test")
        result = handler.send_raw_message("Test message")

        assert result is True
        call_args = mock_post.call_args
        payload = call_args[1]['json']
        assert payload['text'] == "Test message"

    @patch('notification.requests.post')
    def test_send_with_blocks_disabled(self, mock_post):
        """Test sending with blocks disabled uses plain text."""
        mock_post.return_value = MagicMock(status_code=200)

        handler = SlackNotificationHandler(
            webhook_url="https://hooks.slack.com/test",
            use_blocks=False
        )
        handler.send_ticket_alert(event_name="Test Event")

        call_args = mock_post.call_args
        payload = call_args[1]['json']
        assert 'text' in payload
        assert 'blocks' not in payload

    @patch('notification.requests.post')
    def test_send_includes_additional_info(self, mock_post):
        """Test that additional info is included in message."""
        mock_post.return_value = MagicMock(status_code=200)

        handler = SlackNotificationHandler(
            webhook_url="https://hooks.slack.com/test",
            use_blocks=False
        )
        handler.send_ticket_alert(
            event_name="Test Event",
            additional_info={"Date": "2025-03-15", "Age": "21+"}
        )

        call_args = mock_post.call_args
        payload = call_args[1]['json']
        text = payload.get('text', '')
        assert "Date" in text
        assert "2025-03-15" in text


# =============================================================================
# Convenience Function Tests
# =============================================================================

class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    @patch('tasks.notification.requests.post')
    def test_send_ticket_alert_function(self, mock_post):
        """Test the send_ticket_alert convenience function."""
        mock_post.return_value = MagicMock(status_code=200)

        result = send_ticket_alert(
            event_name="Test Event",
            webhook_url="https://hooks.slack.com/test"
        )

        # The function creates a handler and calls send_ticket_alert
        assert result is True
        mock_post.assert_called_once()

    def test_format_changedetection_notification(self):
        """Test changedetection.io notification formatting."""
        result = format_changedetection_notification(
            watch_url="https://tickets.example.com/event",
            watch_title="Concert Name",
            extracted_prices=[{"price": 50, "currency": "USD"}],
            extracted_availability="in_stock",
            change_type="price_change"
        )

        assert isinstance(result, str)
        assert "Concert Name" in result
        assert "50" in result
        assert "Available" in result

    def test_format_changedetection_notification_with_diff(self):
        """Test formatting with diff content."""
        result = format_changedetection_notification(
            watch_url="https://example.com",
            watch_title="Event",
            diff="Some changes here"
        )

        assert "Some changes here" in result

    def test_format_changedetection_notification_truncates_long_diff(self):
        """Test that long diff content is truncated."""
        long_diff = "x" * 1000
        result = format_changedetection_notification(
            watch_url="https://example.com",
            diff=long_diff
        )

        assert len(result) < len(long_diff) + 200  # Should be truncated
        assert "..." in result


# =============================================================================
# Integration-style Tests
# =============================================================================

class TestIntegration:
    """Integration-style tests for the full notification flow."""

    def test_full_message_flow_new_listing(self):
        """Test complete message creation for new listing."""
        builder = TicketAlertMessage()
        builder.set_event("Taylor Swift - Eras Tour", "United Center, Chicago")
        builder.set_prices([
            {"price": 150, "currency": "USD", "label": "Standard"},
            {"price": 350, "currency": "USD", "label": "VIP"},
        ])
        builder.set_url("https://tickets.example.com/taylor-swift")
        builder.set_availability("limited")
        builder.set_change_type("new")
        builder.add_info("Date", "March 15, 2025 8:00 PM")
        builder.add_info("Age", "All Ages")

        # Test text output
        text = builder.build_text()
        assert "Taylor Swift" in text
        assert "United Center" in text
        assert "150" in text
        assert "350" in text
        assert "New Listing" in text
        assert "Limited" in text

        # Test blocks output
        blocks = builder.build_blocks()
        assert len(blocks) > 0

        # Verify structure
        block_types = [b["type"] for b in blocks]
        assert "header" in block_types
        assert "divider" in block_types
        assert "actions" in block_types

    def test_full_message_flow_price_drop(self):
        """Test complete message creation for price drop."""
        builder = TicketAlertMessage()
        builder.set_event("Concert")
        builder.set_prices(
            [{"price": 40, "currency": "USD"}],  # New price
            [{"price": 50, "currency": "USD"}]   # Old price
        )
        builder.set_change_type("price_drop")

        text = builder.build_text()
        assert "Price Drop" in text
        assert "40" in text
        assert "50" in text

    def test_full_message_flow_sellout(self):
        """Test complete message creation for sellout."""
        builder = TicketAlertMessage()
        builder.set_event("Popular Show")
        builder.set_availability("out_of_stock")
        builder.set_change_type("sellout")

        text = builder.build_text()
        assert "SOLD OUT" in text
        assert "Popular Show" in text

    @patch('notification.requests.post')
    def test_complete_handler_flow(self, mock_post):
        """Test complete handler flow from initialization to send."""
        mock_post.return_value = MagicMock(status_code=200)

        # Initialize handler
        handler = SlackNotificationHandler(
            webhook_url="https://hooks.slack.com/test",
            use_blocks=True
        )

        # Send alert
        result = handler.send_ticket_alert(
            event_name="Test Event",
            venue="Test Venue",
            prices=[{"price": 50}],
            url="https://example.com",
            change_type="new"
        )

        assert result is True

        # Verify the payload structure
        call_args = mock_post.call_args
        payload = call_args[1]['json']

        assert 'blocks' in payload
        blocks = payload['blocks']

        # Should have header
        header_blocks = [b for b in blocks if b.get("type") == "header"]
        assert len(header_blocks) >= 1

        # Header should contain event name
        header_text = header_blocks[0]["text"]["text"]
        assert "Test Event" in header_text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
