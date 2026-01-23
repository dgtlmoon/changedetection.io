"""
Custom Slack Notification Handler for TicketWatch

This module provides custom Slack notification formatting for ticket monitoring alerts.
Messages include event name, venue, prices, and URL with rich formatting.

Features:
- Rich formatting with separators and emojis
- Links formatted as Slack link markup (<URL|text>)
- Support for different alert types (new listing, price change, sellout, restock)
- Color-coded messages based on change type

Usage:
    from tasks.notification import SlackNotificationHandler

    handler = SlackNotificationHandler(webhook_url="https://hooks.slack.com/...")
    handler.send_ticket_alert(
        event_name="Concert Name",
        venue="Venue Name",
        prices=[{"price": 50.00, "currency": "USD"}],
        url="https://tickets.example.com/event",
        change_type="new"
    )
"""

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

# Try to use loguru if available
try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)


# =============================================================================
# Slack Message Formatting Utilities
# =============================================================================


def format_slack_link(url: str, text: str | None = None) -> str:
    """
    Format a URL using Slack's link markup.

    Args:
        url: The URL to link to
        text: Optional display text. If None, URL is shown.

    Returns:
        Slack-formatted link: <URL|text> or <URL>

    Examples:
        >>> format_slack_link("https://example.com")
        '<https://example.com>'
        >>> format_slack_link("https://example.com", "Example")
        '<https://example.com|Example>'
    """
    if text:
        return f"<{url}|{text}>"
    return f"<{url}>"


def format_price(price: float | int | str, currency: str = "USD") -> str:
    """
    Format a price value with currency symbol.

    Args:
        price: The price value
        currency: Currency code (USD, EUR, GBP, etc.)

    Returns:
        Formatted price string
    """
    currency_symbols = {
        "USD": "$",
        "EUR": "€",
        "GBP": "£",
        "CAD": "C$",
        "AUD": "A$",
        "JPY": "¥",
    }

    symbol = currency_symbols.get(currency.upper(), currency + " ")

    if isinstance(price, int | float):
        return f"{symbol}{price:.2f}"
    return f"{symbol}{price}"


def format_price_range(prices: list[dict[str, Any]]) -> str:
    """
    Format a list of prices into a readable range.

    Args:
        prices: List of price dictionaries with 'price' and optional 'currency'

    Returns:
        Formatted price range string
    """
    if not prices:
        return "Price not available"

    price_values = []
    currency = "USD"

    for p in prices:
        if isinstance(p, dict):
            val = p.get('price', p.get('value'))
            currency = p.get('currency', currency)
            if val is not None:
                try:
                    price_values.append(float(val))
                except (ValueError, TypeError):
                    pass
        elif isinstance(p, int | float):
            price_values.append(float(p))

    if not price_values:
        return "Price not available"

    min_price = min(price_values)
    max_price = max(price_values)

    if min_price == max_price:
        return format_price(min_price, currency)
    else:
        return f"{format_price(min_price, currency)} - {format_price(max_price, currency)}"


# =============================================================================
# Alert Type Configuration
# =============================================================================


@dataclass
class AlertConfig:
    """Configuration for different alert types."""

    emoji: str
    header: str
    color: str


ALERT_TYPES: dict[str, AlertConfig] = {
    "new": AlertConfig(
        emoji=":ticket:",
        header="New Listing",
        color="#36a64f",  # Green
    ),
    "price_change": AlertConfig(
        emoji=":moneybag:",
        header="Price Change",
        color="#FFA500",  # Orange
    ),
    "price_drop": AlertConfig(
        emoji=":chart_with_downwards_trend:",
        header="Price Drop",
        color="#00FF00",  # Bright green
    ),
    "price_increase": AlertConfig(
        emoji=":chart_with_upwards_trend:",
        header="Price Increase",
        color="#FF6B6B",  # Light red
    ),
    "sellout": AlertConfig(
        emoji=":x:",
        header="SOLD OUT",
        color="#FF0000",  # Red
    ),
    "restock": AlertConfig(
        emoji=":rotating_light:",
        header="RESTOCK ALERT",
        color="#00FF00",  # Bright green - high visibility
    ),
    "limited": AlertConfig(
        emoji=":warning:",
        header="Limited Availability",
        color="#FFFF00",  # Yellow
    ),
    "update": AlertConfig(
        emoji=":bell:",
        header="Listing Updated",
        color="#808080",  # Gray
    ),
}


# =============================================================================
# Message Builder
# =============================================================================


class TicketAlertMessage:
    """
    Builder for creating rich Slack ticket alert messages.

    Supports both Block Kit (for rich formatting) and plain text fallback.
    """

    def __init__(self):
        self.event_name: str | None = None
        self.venue: str | None = None
        self.prices: list[dict[str, Any]] = []
        self.old_prices: list[dict[str, Any]] = []
        self.url: str | None = None
        self.availability: str | None = None
        self.change_type: str = "update"
        self.additional_info: dict[str, str] = {}

    def set_event(self, name: str, venue: str | None = None) -> 'TicketAlertMessage':
        """Set event name and optional venue."""
        self.event_name = name
        self.venue = venue
        return self

    def set_prices(
        self, prices: list[dict[str, Any]], old_prices: list[dict[str, Any]] | None = None
    ) -> 'TicketAlertMessage':
        """Set current and optionally previous prices."""
        self.prices = prices or []
        self.old_prices = old_prices or []
        return self

    def set_url(self, url: str) -> 'TicketAlertMessage':
        """Set the ticket URL."""
        self.url = url
        return self

    def set_availability(self, status: str) -> 'TicketAlertMessage':
        """Set availability status (in_stock, out_of_stock, limited, unknown)."""
        self.availability = status
        return self

    def set_change_type(self, change_type: str) -> 'TicketAlertMessage':
        """Set the type of change (new, price_change, sellout, restock, update)."""
        self.change_type = change_type
        return self

    def add_info(self, key: str, value: str) -> 'TicketAlertMessage':
        """Add additional information field."""
        self.additional_info[key] = value
        return self

    def build_text(self) -> str:
        """
        Build a plain text message with Slack mrkdwn formatting.

        Returns:
            Formatted message text
        """
        lines = []
        alert_config = ALERT_TYPES.get(self.change_type, ALERT_TYPES["update"])

        # Header
        lines.append(f"{alert_config.emoji} *{alert_config.header}*")
        lines.append("━" * 40)

        # Event name
        if self.event_name:
            lines.append(f":star: *Event:* {self.event_name}")

        # Venue
        if self.venue:
            lines.append(f":round_pushpin: *Venue:* {self.venue}")

        # Availability
        if self.availability:
            availability_info = {
                "in_stock": (":white_check_mark:", "Available"),
                "out_of_stock": (":no_entry:", "Sold Out"),
                "limited": (":warning:", "Limited Availability"),
                "unknown": (":question:", "Unknown"),
            }
            emoji, text = availability_info.get(
                self.availability.lower(), (":question:", self.availability)
            )
            lines.append(f"{emoji} *Status:* {text}")

        # Prices section
        if self.prices:
            lines.append("")
            lines.append(":money_with_wings: *Prices:*")

            # Show price change if we have old prices
            if self.old_prices and self.change_type in (
                "price_change",
                "price_drop",
                "price_increase",
            ):
                old_range = format_price_range(self.old_prices)
                new_range = format_price_range(self.prices)
                lines.append(f"  ~{old_range}~ → *{new_range}*")
            else:
                for price_info in self.prices:
                    if isinstance(price_info, dict):
                        price = price_info.get('price', price_info.get('value', '?'))
                        currency = price_info.get('currency', 'USD')
                        label = price_info.get('label', '')
                        formatted = format_price(price, currency)

                        if label:
                            lines.append(f"  • {label}: {formatted}")
                        else:
                            lines.append(f"  • {formatted}")
                    else:
                        lines.append(f"  • {price_info}")

        # Additional info
        for key, value in self.additional_info.items():
            lines.append(f":information_source: *{key}:* {value}")

        # Separator
        lines.append("━" * 40)

        # URL
        if self.url:
            lines.append(f":link: {format_slack_link(self.url, 'View Tickets')}")

        # Timestamp
        lines.append(f":robot_face: _TicketWatch • {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_")

        return "\n".join(lines)

    def build_blocks(self) -> list[dict[str, Any]]:
        """
        Build Slack Block Kit blocks for rich formatting.

        Returns:
            List of Slack block dictionaries
        """
        blocks = []
        alert_config = ALERT_TYPES.get(self.change_type, ALERT_TYPES["update"])

        # Header block
        header_text = f"{alert_config.emoji} {alert_config.header}"
        if self.event_name:
            header_text += f": {self.event_name[:100]}"

        blocks.append(
            {"type": "header", "text": {"type": "plain_text", "text": header_text, "emoji": True}}
        )

        # Divider
        blocks.append({"type": "divider"})

        # Event details section
        fields = []

        if self.venue:
            fields.append({"type": "mrkdwn", "text": f":round_pushpin: *Venue:*\n{self.venue}"})

        if self.availability:
            availability_info = {
                "in_stock": (":white_check_mark:", "Available"),
                "out_of_stock": (":no_entry:", "Sold Out"),
                "limited": (":warning:", "Limited"),
                "unknown": (":question:", "Unknown"),
            }
            emoji, text = availability_info.get(
                self.availability.lower(), (":question:", self.availability)
            )
            fields.append({"type": "mrkdwn", "text": f"{emoji} *Status:*\n{text}"})

        if fields:
            blocks.append({"type": "section", "fields": fields})

        # Prices section
        if self.prices:
            price_text = ":money_with_wings: *Prices:*\n"

            if self.old_prices and self.change_type in (
                "price_change",
                "price_drop",
                "price_increase",
            ):
                old_range = format_price_range(self.old_prices)
                new_range = format_price_range(self.prices)
                price_text += f"~{old_range}~ → *{new_range}*"
            else:
                price_lines = []
                for price_info in self.prices:
                    if isinstance(price_info, dict):
                        price = price_info.get('price', price_info.get('value', '?'))
                        currency = price_info.get('currency', 'USD')
                        label = price_info.get('label', '')
                        formatted = format_price(price, currency)

                        if label:
                            price_lines.append(f"• {label}: {formatted}")
                        else:
                            price_lines.append(f"• {formatted}")
                    else:
                        price_lines.append(f"• {price_info}")

                price_text += "\n".join(price_lines)

            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": price_text}})

        # Additional info
        for key, value in self.additional_info.items():
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f":information_source: *{key}:* {value}"},
                }
            )

        # Divider before actions
        blocks.append({"type": "divider"})

        # URL button
        if self.url:
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": ":link: View Tickets",
                                "emoji": True,
                            },
                            "url": self.url,
                            "style": "primary",
                        }
                    ],
                }
            )

        # Context footer
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f":robot_face: TicketWatch | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    }
                ],
            }
        )

        return blocks

    def build_attachment(self) -> dict[str, Any]:
        """
        Build a Slack attachment (for color-coded messages).

        Returns:
            Slack attachment dictionary
        """
        alert_config = ALERT_TYPES.get(self.change_type, ALERT_TYPES["update"])

        return {
            "color": alert_config.color,
            "fallback": self.build_text(),
            "blocks": self.build_blocks(),
        }


# =============================================================================
# Slack Notification Handler
# =============================================================================


class SlackNotificationHandler:
    """
    Handler for sending ticket alerts to Slack.

    Supports:
    - Webhook URLs
    - Block Kit formatting
    - Plain text fallback
    - Rate limiting awareness
    """

    def __init__(
        self,
        webhook_url: str | None = None,
        default_channel: str | None = None,
        use_blocks: bool = True,
    ):
        """
        Initialize the Slack notification handler.

        Args:
            webhook_url: Slack webhook URL. If not provided, reads from SLACK_WEBHOOK_URL env var.
            default_channel: Default channel to post to (optional, webhook determines this).
            use_blocks: Whether to use Block Kit formatting (default True).
        """
        self.webhook_url = webhook_url or os.getenv('SLACK_WEBHOOK_URL')
        self.default_channel = default_channel
        self.use_blocks = use_blocks

        if not self.webhook_url:
            logger.warning("No Slack webhook URL configured. Notifications will not be sent.")

    def send_ticket_alert(
        self,
        event_name: str,
        venue: str | None = None,
        prices: list[dict[str, Any]] | None = None,
        old_prices: list[dict[str, Any]] | None = None,
        url: str | None = None,
        availability: str | None = None,
        change_type: str = "update",
        additional_info: dict[str, str] | None = None,
    ) -> bool:
        """
        Send a ticket alert notification to Slack.

        Args:
            event_name: Name of the event
            venue: Venue name (optional)
            prices: List of current price dictionaries
            old_prices: List of previous price dictionaries (for price change alerts)
            url: Link to ticket page
            availability: Status (in_stock, out_of_stock, limited, unknown)
            change_type: Type of alert (new, price_change, sellout, restock, update)
            additional_info: Extra fields to include

        Returns:
            True if sent successfully, False otherwise
        """
        if not self.webhook_url:
            logger.error("Cannot send notification: No webhook URL configured")
            return False

        # Build the message
        builder = TicketAlertMessage()
        builder.set_event(event_name, venue)
        builder.set_prices(prices or [], old_prices)
        builder.set_url(url)
        builder.set_availability(availability)
        builder.set_change_type(change_type)

        if additional_info:
            for key, value in additional_info.items():
                builder.add_info(key, value)

        # Build payload
        if self.use_blocks:
            payload = {"blocks": builder.build_blocks()}
        else:
            payload = {"text": builder.build_text()}

        if self.default_channel:
            payload["channel"] = self.default_channel

        return self._send_webhook(payload)

    def send_raw_message(self, text: str, blocks: list[dict] | None = None) -> bool:
        """
        Send a raw message to Slack.

        Args:
            text: Plain text message (fallback for blocks)
            blocks: Optional Block Kit blocks

        Returns:
            True if sent successfully, False otherwise
        """
        if not self.webhook_url:
            logger.error("Cannot send notification: No webhook URL configured")
            return False

        payload = {"text": text}
        if blocks:
            payload["blocks"] = blocks

        return self._send_webhook(payload)

    def _send_webhook(self, payload: dict[str, Any]) -> bool:
        """
        Send a payload to the Slack webhook.

        Args:
            payload: JSON-serializable payload

        Returns:
            True if successful, False otherwise
        """
        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )

            if response.status_code == 200:
                logger.debug("Slack notification sent successfully")
                return True
            else:
                logger.error(f"Slack webhook returned {response.status_code}: {response.text}")
                return False

        except requests.exceptions.Timeout:
            logger.error("Slack webhook request timed out")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send Slack notification: {e}")
            return False


# =============================================================================
# Convenience Functions
# =============================================================================


def send_ticket_alert(
    event_name: str,
    venue: str | None = None,
    prices: list[dict[str, Any]] | None = None,
    url: str | None = None,
    availability: str | None = None,
    change_type: str = "update",
    webhook_url: str | None = None,
) -> bool:
    """
    Convenience function to send a ticket alert.

    Args:
        event_name: Name of the event
        venue: Venue name (optional)
        prices: List of price dictionaries
        url: Link to ticket page
        availability: Availability status
        change_type: Type of alert
        webhook_url: Optional webhook URL (defaults to SLACK_WEBHOOK_URL env var)

    Returns:
        True if sent successfully, False otherwise

    Example:
        >>> send_ticket_alert(
        ...     event_name="Taylor Swift - Eras Tour",
        ...     venue="United Center, Chicago",
        ...     prices=[{"price": 150, "currency": "USD"}, {"price": 350, "currency": "USD"}],
        ...     url="https://tickets.example.com/taylor-swift",
        ...     availability="limited",
        ...     change_type="restock"
        ... )
    """
    handler = SlackNotificationHandler(webhook_url=webhook_url)
    return handler.send_ticket_alert(
        event_name=event_name,
        venue=venue,
        prices=prices,
        url=url,
        availability=availability,
        change_type=change_type,
    )


def format_changedetection_notification(
    watch_url: str,
    watch_title: str | None = None,
    diff: str | None = None,
    extracted_prices: list[dict[str, Any]] | None = None,
    extracted_availability: str | None = None,
    change_type: str = "update",
) -> str:
    """
    Format a changedetection.io notification for Slack.

    This function is designed to be used in changedetection.io's
    notification templates.

    Args:
        watch_url: The URL being watched
        watch_title: Title of the watch (event name)
        diff: The diff content
        extracted_prices: Extracted price data from pg_store
        extracted_availability: Extracted availability status
        change_type: Type of change

    Returns:
        Formatted Slack message text

    Example usage in changedetection.io notification body:
        {{ watch_url }} changed!
        {% if extracted_prices %}
        Prices: {{ extracted_prices | join(', ') }}
        {% endif %}
    """
    builder = TicketAlertMessage()
    builder.set_event(watch_title or "Watched Page", None)
    builder.set_url(watch_url)

    if extracted_prices:
        builder.set_prices(extracted_prices)

    if extracted_availability:
        builder.set_availability(extracted_availability)

    builder.set_change_type(change_type)

    if diff:
        builder.add_info("Changes", diff[:500] + "..." if len(diff) > 500 else diff)

    return builder.build_text()


# =============================================================================
# CLI Testing
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test Slack notifications")
    parser.add_argument("--webhook", help="Slack webhook URL (or set SLACK_WEBHOOK_URL)")
    parser.add_argument("--test", action="store_true", help="Send a test notification")
    args = parser.parse_args()

    if args.test:
        webhook = args.webhook or os.getenv('SLACK_WEBHOOK_URL')
        if not webhook:
            print("Error: No webhook URL provided. Use --webhook or set SLACK_WEBHOOK_URL")
            exit(1)

        handler = SlackNotificationHandler(webhook_url=webhook)

        # Send test notification
        success = handler.send_ticket_alert(
            event_name="Test Event - TicketWatch",
            venue="Test Venue, Chicago IL",
            prices=[
                {"price": 49.99, "currency": "USD", "label": "General Admission"},
                {"price": 99.99, "currency": "USD", "label": "VIP"},
            ],
            url="https://example.com/tickets/test-event",
            availability="in_stock",
            change_type="new",
            additional_info={"Date": "2025-03-15 8:00 PM", "Age": "21+"},
        )

        if success:
            print("Test notification sent successfully!")
        else:
            print("Failed to send test notification")
            exit(1)
    else:
        # Print example message
        builder = TicketAlertMessage()
        builder.set_event("Example Concert", "Example Venue")
        builder.set_prices([{"price": 50, "currency": "USD"}])
        builder.set_url("https://example.com")
        builder.set_availability("in_stock")
        builder.set_change_type("new")

        print("Example notification message:")
        print("-" * 50)
        print(builder.build_text())
