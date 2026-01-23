"""
Price Change Alert Service for TicketWatch/ATC Page Monitor

This module provides Slack alerts when ticket prices change. It detects when
current_price_low or current_price_high changes and sends notifications with
old/new prices, percentage change, and direction indicators.

Features:
- Detects when current_price_low or current_price_high changes
- Calculates percentage change with direction emoji
- Configurable threshold to avoid noise from minor changes (default: 1%)
- Uses distinct alert types for price drops vs increases
- Includes all event details: name, artist, venue, date, time, prices, link
- Routes alerts to all tag webhooks for the event
- Logs all price change alerts with type='price_change' in notification_log

Usage:
    from tasks.price_change_alert import PriceChangeAlertService
    from tasks.postgresql_store import PostgreSQLStore

    store = PostgreSQLStore(database_url=os.getenv('DATABASE_URL'))
    await store.initialize()

    service = PriceChangeAlertService(
        store=store,
        default_webhook_url=os.getenv('DEFAULT_SLACK_WEBHOOK'),
        min_percent_threshold=1.0  # Only alert on >= 1% changes
    )

    # Check for price change and send alert if detected
    result = await service.check_and_alert_price_change(
        event_uuid="...",
        old_price_low=100.00,
        old_price_high=200.00,
        new_price_low=90.00,
        new_price_high=180.00
    )
"""

import uuid as uuid_builder
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

from tasks.models import Event
from tasks.notification_router import (
    NotificationRoutingResult,
    TagNotificationRouter,
)

# =============================================================================
# Constants
# =============================================================================

# Default minimum percentage change to trigger an alert (1% = avoid minor noise)
DEFAULT_MIN_PERCENT_THRESHOLD = 1.0

# Emojis for price direction
PRICE_UP_EMOJI = ":chart_with_upwards_trend:"
PRICE_DOWN_EMOJI = ":chart_with_downwards_trend:"
PRICE_CHANGE_EMOJI = ":moneybag:"


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class PriceChangeInfo:
    """Information about a price change."""

    old_price_low: Decimal | float | None
    old_price_high: Decimal | float | None
    new_price_low: Decimal | float | None
    new_price_high: Decimal | float | None

    @property
    def has_change(self) -> bool:
        """Check if any price changed."""
        low_changed = self.old_price_low != self.new_price_low
        high_changed = self.old_price_high != self.new_price_high
        return low_changed or high_changed

    @property
    def low_price_change(self) -> tuple[float | None, float | None]:
        """Get (absolute_change, percent_change) for low price."""
        return self._calculate_change(self.old_price_low, self.new_price_low)

    @property
    def high_price_change(self) -> tuple[float | None, float | None]:
        """Get (absolute_change, percent_change) for high price."""
        return self._calculate_change(self.old_price_high, self.new_price_high)

    @property
    def primary_change(self) -> tuple[float | None, float | None]:
        """
        Get the most significant change (absolute, percent).

        Uses low price change if available, otherwise high price.
        """
        abs_low, pct_low = self.low_price_change
        abs_high, pct_high = self.high_price_change

        # Prefer low price change if it exists
        if pct_low is not None:
            return abs_low, pct_low
        return abs_high, pct_high

    @property
    def direction(self) -> str:
        """
        Get overall direction of price change.

        Returns: 'up', 'down', or 'mixed'
        """
        abs_change, _ = self.primary_change
        if abs_change is None:
            return 'mixed'
        if abs_change > 0:
            return 'up'
        elif abs_change < 0:
            return 'down'
        return 'mixed'

    @property
    def direction_emoji(self) -> str:
        """Get emoji for price direction."""
        direction = self.direction
        if direction == 'up':
            return PRICE_UP_EMOJI
        elif direction == 'down':
            return PRICE_DOWN_EMOJI
        return PRICE_CHANGE_EMOJI

    @property
    def notification_type(self) -> str:
        """Get notification type based on direction."""
        direction = self.direction
        if direction == 'up':
            return 'price_increase'
        elif direction == 'down':
            return 'price_drop'
        return 'price_change'

    def _calculate_change(
        self, old_price: Decimal | float | None, new_price: Decimal | float | None
    ) -> tuple[float | None, float | None]:
        """
        Calculate absolute and percentage change between prices.

        Returns:
            Tuple of (absolute_change, percent_change).
            Negative values indicate price decrease.
        """
        if old_price is None or new_price is None:
            return None, None

        old_val = float(old_price)
        new_val = float(new_price)

        if old_val == 0:
            return new_val, None

        abs_change = new_val - old_val
        pct_change = (abs_change / old_val) * 100

        return abs_change, pct_change

    def exceeds_threshold(self, threshold_percent: float) -> bool:
        """
        Check if any price change exceeds the given threshold.

        Args:
            threshold_percent: Minimum percentage change to consider significant

        Returns:
            True if any price changed by >= threshold_percent
        """
        _, pct_low = self.low_price_change
        _, pct_high = self.high_price_change

        if pct_low is not None and abs(pct_low) >= threshold_percent:
            return True
        if pct_high is not None and abs(pct_high) >= threshold_percent:
            return True

        return False

    def format_change_summary(self) -> str:
        """
        Format a human-readable change summary.

        Returns:
            String like "$100 -> $90 (-10.0%)" or "Price changed"
        """
        parts = []

        # Low price change
        _, pct_low = self.low_price_change
        if self.old_price_low is not None and self.new_price_low is not None:
            old_str = f"${float(self.old_price_low):.2f}"
            new_str = f"${float(self.new_price_low):.2f}"
            if pct_low is not None:
                sign = '+' if pct_low > 0 else ''
                parts.append(f"Low: {old_str} -> {new_str} ({sign}{pct_low:.1f}%)")
            else:
                parts.append(f"Low: {old_str} -> {new_str}")

        # High price change
        _, pct_high = self.high_price_change
        if self.old_price_high is not None and self.new_price_high is not None:
            if self.old_price_high != self.old_price_low or self.new_price_high != self.new_price_low:
                old_str = f"${float(self.old_price_high):.2f}"
                new_str = f"${float(self.new_price_high):.2f}"
                if pct_high is not None:
                    sign = '+' if pct_high > 0 else ''
                    parts.append(f"High: {old_str} -> {new_str} ({sign}{pct_high:.1f}%)")
                else:
                    parts.append(f"High: {old_str} -> {new_str}")

        return ' | '.join(parts) if parts else 'Price changed'


@dataclass
class PriceChangeAlertResult:
    """Result of a price change alert check and notification."""

    event_id: str
    is_price_change: bool
    exceeds_threshold: bool
    alert_sent: bool
    price_info: PriceChangeInfo | None = None
    notification_result: NotificationRoutingResult | None = None
    error_message: str | None = None

    @property
    def success(self) -> bool:
        """Check if price change was detected and alert was successfully sent."""
        return self.is_price_change and self.exceeds_threshold and self.alert_sent

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/debugging."""
        return {
            'event_id': self.event_id,
            'is_price_change': self.is_price_change,
            'exceeds_threshold': self.exceeds_threshold,
            'alert_sent': self.alert_sent,
            'price_info': {
                'old_price_low': float(self.price_info.old_price_low)
                if self.price_info and self.price_info.old_price_low
                else None,
                'old_price_high': float(self.price_info.old_price_high)
                if self.price_info and self.price_info.old_price_high
                else None,
                'new_price_low': float(self.price_info.new_price_low)
                if self.price_info and self.price_info.new_price_low
                else None,
                'new_price_high': float(self.price_info.new_price_high)
                if self.price_info and self.price_info.new_price_high
                else None,
                'direction': self.price_info.direction if self.price_info else None,
                'change_summary': self.price_info.format_change_summary()
                if self.price_info
                else None,
            }
            if self.price_info
            else None,
            'notification_result': self.notification_result.to_dict()
            if self.notification_result
            else None,
            'error_message': self.error_message,
        }


# =============================================================================
# Price Change Alert Service
# =============================================================================


class PriceChangeAlertService:
    """
    Service for detecting price changes and sending Slack alerts.

    This service monitors ticket price changes and sends notifications
    when prices change by more than a configurable threshold.

    Key features:
    - Detects both price increases and decreases
    - Calculates percentage change with direction indicator
    - Configurable threshold to filter minor fluctuations (default: 1%)
    - Distinct message formatting for price drops vs increases
    - All event details included (name, artist, venue, date, time, prices, URL)
    - Routes to all configured tag webhooks
    - Full audit logging to notification_log table

    Attributes:
        store: PostgreSQLStore instance for database access
        default_webhook_url: Fallback webhook URL when no tag webhooks exist
        min_percent_threshold: Minimum percentage change to trigger alert
        router: TagNotificationRouter for webhook delivery
    """

    def __init__(
        self,
        store,
        default_webhook_url: str | None = None,
        min_percent_threshold: float = DEFAULT_MIN_PERCENT_THRESHOLD,
    ):
        """
        Initialize the price change alert service.

        Args:
            store: PostgreSQLStore instance (must be initialized)
            default_webhook_url: Fallback Slack webhook URL when no tag webhooks exist
            min_percent_threshold: Minimum percentage change to trigger alert (default: 1%)
        """
        self.store = store
        self.default_webhook_url = default_webhook_url
        self.min_percent_threshold = min_percent_threshold
        self.router = TagNotificationRouter(
            store=store,
            default_webhook_url=default_webhook_url,
            use_blocks=True,
        )

    def is_significant_change(
        self,
        old_price_low: Decimal | float | None,
        old_price_high: Decimal | float | None,
        new_price_low: Decimal | float | None,
        new_price_high: Decimal | float | None,
    ) -> tuple[bool, PriceChangeInfo]:
        """
        Determine if a price change is significant enough to alert.

        Args:
            old_price_low: Previous low price
            old_price_high: Previous high price
            new_price_low: Current low price
            new_price_high: Current high price

        Returns:
            Tuple of (is_significant, PriceChangeInfo)
        """
        price_info = PriceChangeInfo(
            old_price_low=old_price_low,
            old_price_high=old_price_high,
            new_price_low=new_price_low,
            new_price_high=new_price_high,
        )

        if not price_info.has_change:
            return False, price_info

        is_significant = price_info.exceeds_threshold(self.min_percent_threshold)
        return is_significant, price_info

    async def check_and_alert_price_change(
        self,
        event_uuid: str,
        old_price_low: Decimal | float | None,
        old_price_high: Decimal | float | None,
        new_price_low: Decimal | float | None,
        new_price_high: Decimal | float | None,
        event_data: dict[str, Any] | None = None,
    ) -> PriceChangeAlertResult:
        """
        Check for price change and send alert if significant.

        This is the main entry point for price change detection. Call this method
        whenever an event's prices are updated.

        Args:
            event_uuid: UUID of the event
            old_price_low: Previous low price
            old_price_high: Previous high price
            new_price_low: Current low price
            new_price_high: Current high price
            event_data: Optional dict with event details. If not provided,
                       will be fetched from database.

        Returns:
            PriceChangeAlertResult with detection and notification details
        """
        result = PriceChangeAlertResult(
            event_id=event_uuid,
            is_price_change=False,
            exceeds_threshold=False,
            alert_sent=False,
        )

        # Check if this is a significant price change
        is_significant, price_info = self.is_significant_change(
            old_price_low=old_price_low,
            old_price_high=old_price_high,
            new_price_low=new_price_low,
            new_price_high=new_price_high,
        )

        result.price_info = price_info
        result.is_price_change = price_info.has_change

        if not price_info.has_change:
            logger.debug(f"Event {event_uuid}: No price change detected")
            return result

        if not is_significant:
            _, pct = price_info.primary_change
            logger.debug(
                f"Event {event_uuid}: Price change below threshold "
                f"({pct:.2f}% < {self.min_percent_threshold}%)"
            )
            return result

        result.exceeds_threshold = True
        logger.info(
            f"PRICE CHANGE DETECTED for event {event_uuid}! "
            f"Direction: {price_info.direction}, {price_info.format_change_summary()}"
        )

        # Get event data if not provided
        if event_data is None:
            event_data = await self._fetch_event_data(event_uuid)
            if event_data is None:
                result.error_message = f"Event {event_uuid} not found in database"
                logger.error(result.error_message)
                return result

        # Send price change alert
        try:
            notification_result = await self._send_price_change_alert(
                event_uuid, event_data, price_info
            )
            result.notification_result = notification_result
            result.alert_sent = notification_result.any_successful

            if result.alert_sent:
                logger.info(
                    f"Price change alert sent for event {event_uuid}: "
                    f"{notification_result.successful_deliveries}/{notification_result.total_webhooks} webhooks"
                )
            else:
                logger.warning(
                    f"Price change alert failed for event {event_uuid}: "
                    f"0/{notification_result.total_webhooks} webhooks succeeded"
                )

        except Exception as e:
            result.error_message = f"Failed to send price change alert: {str(e)}"
            logger.exception(f"Error sending price change alert for event {event_uuid}")

        return result

    async def process_price_change(
        self,
        event_uuid: str,
        old_price_low: Decimal | float | None,
        old_price_high: Decimal | float | None,
        new_price_low: Decimal | float | None,
        new_price_high: Decimal | float | None,
        event_data: dict[str, Any] | None = None,
    ) -> PriceChangeAlertResult:
        """
        Process a price change and send alert if applicable.

        This is an alias for check_and_alert_price_change for API compatibility.

        Args:
            event_uuid: UUID of the event
            old_price_low: Previous low price
            old_price_high: Previous high price
            new_price_low: Current low price
            new_price_high: Current high price
            event_data: Optional event details dict

        Returns:
            PriceChangeAlertResult with detection and notification details
        """
        return await self.check_and_alert_price_change(
            event_uuid=event_uuid,
            old_price_low=old_price_low,
            old_price_high=old_price_high,
            new_price_low=new_price_low,
            new_price_high=new_price_high,
            event_data=event_data,
        )

    async def _fetch_event_data(self, event_uuid: str) -> dict[str, Any] | None:
        """
        Fetch event data from the database.

        Args:
            event_uuid: UUID of the event

        Returns:
            Dict with event data, or None if not found
        """
        try:
            async with self.store.session() as session:
                event_id = uuid_builder.UUID(event_uuid)
                event = await Event.get_by_id(session, event_id)

                if event is None:
                    return None

                return {
                    'event_name': event.event_name,
                    'artist': event.artist,
                    'venue': event.venue,
                    'event_date': event.event_date.isoformat() if event.event_date else None,
                    'event_time': event.event_time.isoformat() if event.event_time else None,
                    'current_price_low': float(event.current_price_low)
                    if event.current_price_low
                    else None,
                    'current_price_high': float(event.current_price_high)
                    if event.current_price_high
                    else None,
                    'url': event.url,
                    'is_sold_out': event.is_sold_out,
                }

        except Exception as e:
            logger.error(f"Failed to fetch event data for {event_uuid}: {e}")
            return None

    def _build_price_list(
        self,
        price_low: Decimal | float | None,
        price_high: Decimal | float | None,
    ) -> list[dict[str, Any]]:
        """Build a price list for notification from low/high values."""
        prices = []
        if price_low:
            price_entry: dict[str, Any] = {'price': float(price_low), 'currency': 'USD'}
            if price_high and price_high != price_low:
                price_entry['label'] = 'From'
            prices.append(price_entry)

        if price_high and price_high != price_low:
            prices.append({'price': float(price_high), 'currency': 'USD', 'label': 'To'})

        return prices

    def _build_additional_info(
        self,
        event_data: dict[str, Any],
        price_info: PriceChangeInfo,
    ) -> dict[str, str]:
        """Build additional info dict for the notification."""
        additional_info: dict[str, str] = {}
        _, pct_change = price_info.primary_change

        # Price change direction and percentage
        if pct_change is not None:
            sign = '+' if pct_change > 0 else ''
            direction_text = 'Price Increase' if pct_change > 0 else 'Price Drop'
            additional_info['Change'] = (
                f"{price_info.direction_emoji} {direction_text} ({sign}{pct_change:.1f}%)"
            )
        else:
            additional_info['Change'] = f"{price_info.direction_emoji} {price_info.format_change_summary()}"

        # Event date/time
        if event_data.get('event_date'):
            date_str = event_data['event_date']
            if event_data.get('event_time'):
                date_str += f" at {event_data['event_time']}"
            additional_info['Date'] = date_str

        # Artist (if separate from event name)
        if event_data.get('artist') and event_data.get('event_name'):
            additional_info['Artist'] = event_data['artist']

        return additional_info

    async def _send_price_change_alert(
        self,
        event_uuid: str,
        event_data: dict[str, Any],
        price_info: PriceChangeInfo,
    ) -> NotificationRoutingResult:
        """
        Send price change alert to all configured webhooks.

        Args:
            event_uuid: UUID of the event
            event_data: Dict with event details
            price_info: Price change information

        Returns:
            NotificationRoutingResult with delivery details
        """
        prices = self._build_price_list(price_info.new_price_low, price_info.new_price_high)
        old_prices = self._build_price_list(price_info.old_price_low, price_info.old_price_high)

        # Build event display name
        event_name = event_data.get('event_name') or 'Event'
        if event_data.get('artist'):
            event_name = f"{event_data['artist']} - {event_name}"

        additional_info = self._build_additional_info(event_data, price_info)

        # Determine availability
        availability = None
        if event_data.get('is_sold_out'):
            availability = 'out_of_stock'
        elif event_data.get('is_sold_out') is False:
            availability = 'in_stock'

        # Send notification via router (handles all tag webhooks)
        result = await self.router.send_event_notification(
            event_uuid=event_uuid,
            notification_type=price_info.notification_type,  # price_drop, price_increase, or price_change
            event_name=event_name,
            venue=event_data.get('venue'),
            prices=prices,
            old_prices=old_prices,
            url=event_data.get('url'),
            availability=availability,
            additional_info=additional_info,
        )

        return result


# =============================================================================
# Convenience Functions
# =============================================================================


async def send_price_change_alert(
    store,
    event_uuid: str,
    old_price_low: Decimal | float | None,
    old_price_high: Decimal | float | None,
    new_price_low: Decimal | float | None,
    new_price_high: Decimal | float | None,
    event_data: dict[str, Any] | None = None,
    default_webhook_url: str | None = None,
    min_percent_threshold: float = DEFAULT_MIN_PERCENT_THRESHOLD,
) -> PriceChangeAlertResult:
    """
    Convenience function to check for price change and send alert.

    Args:
        store: PostgreSQLStore instance
        event_uuid: UUID of the event
        old_price_low: Previous low price
        old_price_high: Previous high price
        new_price_low: Current low price
        new_price_high: Current high price
        event_data: Optional dict with event details
        default_webhook_url: Fallback webhook URL
        min_percent_threshold: Minimum percentage change to trigger alert

    Returns:
        PriceChangeAlertResult with detection and delivery details

    Example:
        result = await send_price_change_alert(
            store=store,
            event_uuid="abc-123",
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=90.00,
            new_price_high=180.00,
        )
        if result.success:
            print(f"Price change alert sent! Direction: {result.price_info.direction}")
    """
    service = PriceChangeAlertService(
        store=store,
        default_webhook_url=default_webhook_url,
        min_percent_threshold=min_percent_threshold,
    )

    return await service.check_and_alert_price_change(
        event_uuid=event_uuid,
        old_price_low=old_price_low,
        old_price_high=old_price_high,
        new_price_low=new_price_low,
        new_price_high=new_price_high,
        event_data=event_data,
    )


async def check_price_change_for_alert(
    store,
    event_uuid: str,
    old_price_low: Decimal | float | None,
    old_price_high: Decimal | float | None,
    new_price_low: Decimal | float | None,
    new_price_high: Decimal | float | None,
    event_data: dict[str, Any] | None = None,
    default_webhook_url: str | None = None,
    min_percent_threshold: float = DEFAULT_MIN_PERCENT_THRESHOLD,
) -> PriceChangeAlertResult:
    """
    Check a price change and send alert if applicable.

    This is the recommended entry point for integrating price change alerts
    into your monitoring flow. Call this whenever prices change.

    Args:
        store: PostgreSQLStore instance
        event_uuid: UUID of the event
        old_price_low: Previous low price
        old_price_high: Previous high price
        new_price_low: Current low price
        new_price_high: Current high price
        event_data: Optional dict with event details
        default_webhook_url: Fallback webhook URL
        min_percent_threshold: Minimum percentage change to trigger alert

    Returns:
        PriceChangeAlertResult (is_price_change=False if no change)

    Example:
        # In your update worker:
        changes = await event.update_event_data(
            session,
            current_price_low=new_low,
            current_price_high=new_high
        )

        if changes['price_changed']:
            result = await check_price_change_for_alert(
                store=store,
                event_uuid=str(event.id),
                old_price_low=old_low,
                old_price_high=old_high,
                new_price_low=new_low,
                new_price_high=new_high,
            )
            if result.success:
                logger.info(f"Price alert sent: {result.price_info.direction}")
    """
    service = PriceChangeAlertService(
        store=store,
        default_webhook_url=default_webhook_url,
        min_percent_threshold=min_percent_threshold,
    )

    return await service.process_price_change(
        event_uuid=event_uuid,
        old_price_low=old_price_low,
        old_price_high=old_price_high,
        new_price_low=new_price_low,
        new_price_high=new_price_high,
        event_data=event_data,
    )


# =============================================================================
# CLI Testing
# =============================================================================

if __name__ == '__main__':
    import asyncio
    import os

    async def test_price_change_alert():
        """Test the price change alert service."""
        from tasks.postgresql_store import PostgreSQLStore

        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            print('DATABASE_URL environment variable not set')
            return

        default_webhook = os.getenv('SLACK_WEBHOOK_URL')
        if not default_webhook:
            print('SLACK_WEBHOOK_URL environment variable not set')
            print('(Needed for testing default fallback)')

        store = PostgreSQLStore(database_url=database_url)
        await store.initialize()

        try:
            service = PriceChangeAlertService(
                store=store,
                default_webhook_url=default_webhook,
                min_percent_threshold=1.0,  # 1% threshold
            )

            # Test price change detection logic
            print('\n--- Testing Price Change Detection ---')
            test_cases = [
                (100, 200, 90, 180, True, 'down', '10% decrease'),
                (100, 200, 110, 220, True, 'up', '10% increase'),
                (100, 200, 100.5, 201, False, 'up', '<1% change (below threshold)'),
                (100, 200, 100, 200, False, 'mixed', 'No change'),
                (None, 200, None, 180, True, 'down', 'High price only decrease'),
                (100, None, 90, None, True, 'down', 'Low price only decrease'),
            ]

            for old_low, old_high, new_low, new_high, expect_sig, expect_dir, desc in test_cases:
                is_sig, info = service.is_significant_change(old_low, old_high, new_low, new_high)
                status = 'PASS' if is_sig == expect_sig else 'FAIL'
                dir_status = 'PASS' if info.direction == expect_dir else f'FAIL (got {info.direction})'
                print(f'  [{status}] {desc}:')
                print(f'    Significant: {is_sig}, Direction: {info.direction} [{dir_status}]')
                print(f'    Summary: {info.format_change_summary()}')

            # Get a test event
            watches = await store.get_all_watches()
            if not watches:
                print('\nNo watches in database to test with')
                return

            event_uuid = list(watches.keys())[0]
            watch = watches[event_uuid]

            print('\n--- Testing Price Change Alert for Event ---')
            print(f'Event: {watch.get("title") or watch.get("url")}')

            # Simulate a price change alert (10% decrease)
            result = await service.check_and_alert_price_change(
                event_uuid=event_uuid,
                old_price_low=100.00,
                old_price_high=200.00,
                new_price_low=90.00,
                new_price_high=180.00,
            )

            print('\nPrice Change Alert Result:')
            print(f'  Is price change: {result.is_price_change}')
            print(f'  Exceeds threshold: {result.exceeds_threshold}')
            print(f'  Alert sent: {result.alert_sent}')

            if result.price_info:
                print(f'  Direction: {result.price_info.direction}')
                print(f'  Summary: {result.price_info.format_change_summary()}')

            if result.notification_result:
                nr = result.notification_result
                print(f'  Total webhooks: {nr.total_webhooks}')
                print(f'  Successful: {nr.successful_deliveries}')
                print(f'  Failed: {nr.failed_deliveries}')
                print(f'  Used default: {nr.used_default_fallback}')

            if result.error_message:
                print(f'  Error: {result.error_message}')

        finally:
            await store.close()

    asyncio.run(test_price_change_alert())
