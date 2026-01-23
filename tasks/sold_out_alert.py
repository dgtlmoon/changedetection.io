"""
Sold Out Alert Service for TicketWatch/ATC Page Monitor

This module provides Slack alerts when an event sells out. It detects when
is_sold_out changes from false to true and sends notifications with the
last known price.

Features:
- Detects is_sold_out transition from false to true (sell out detection)
- Sends Slack notification with 'Sold Out' message
- Includes last known price in the alert
- Includes all event details: name, artist, venue, date, time, price, link
- Routes alerts to all tag webhooks for the event
- Logs all sold out alerts with type='sold_out' in notification_log

Usage:
    from tasks.sold_out_alert import SoldOutAlertService
    from tasks.postgresql_store import PostgreSQLStore

    store = PostgreSQLStore(database_url=os.getenv('DATABASE_URL'))
    await store.initialize()

    service = SoldOutAlertService(store=store, default_webhook_url=os.getenv('DEFAULT_SLACK_WEBHOOK'))

    # Check for sell out and send alert if detected
    result = await service.check_and_alert_sold_out(
        event_uuid="...",
        previous_is_sold_out=False,
        current_is_sold_out=True
    )

    # Or process availability change directly
    result = await service.process_availability_change(
        event_uuid="...",
        old_is_sold_out=False,
        new_is_sold_out=True,
        event_data={...}  # Optional event details
    )
"""

import uuid as uuid_builder
from dataclasses import dataclass
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
# Data Classes
# =============================================================================


@dataclass
class SoldOutAlertResult:
    """Result of a sold out alert check and notification."""

    event_id: str
    is_sold_out: bool
    alert_sent: bool
    notification_result: NotificationRoutingResult | None = None
    error_message: str | None = None

    @property
    def success(self) -> bool:
        """Check if sold out was detected and alert was successfully sent."""
        return self.is_sold_out and self.alert_sent

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/debugging."""
        return {
            'event_id': self.event_id,
            'is_sold_out': self.is_sold_out,
            'alert_sent': self.alert_sent,
            'notification_result': self.notification_result.to_dict()
            if self.notification_result
            else None,
            'error_message': self.error_message,
        }


# =============================================================================
# Sold Out Alert Service
# =============================================================================


class SoldOutAlertService:
    """
    Service for detecting sell outs and sending Slack alerts.

    This service monitors availability changes and sends notifications when
    an event sells out (is_sold_out changes from False to True).

    Key features:
    - Detects when tickets become unavailable
    - Includes last known price in notification
    - All event details included (name, artist, venue, date, time, price, URL)
    - Routes to all configured tag webhooks
    - Full audit logging to notification_log table

    Attributes:
        store: PostgreSQLStore instance for database access
        default_webhook_url: Fallback webhook URL when no tag webhooks exist
        router: TagNotificationRouter for webhook delivery
    """

    def __init__(
        self,
        store,
        default_webhook_url: str | None = None,
    ):
        """
        Initialize the sold out alert service.

        Args:
            store: PostgreSQLStore instance (must be initialized)
            default_webhook_url: Fallback Slack webhook URL when no tag webhooks exist
        """
        self.store = store
        self.default_webhook_url = default_webhook_url
        self.router = TagNotificationRouter(
            store=store,
            default_webhook_url=default_webhook_url,
            use_blocks=True,
        )

    def is_sell_out(self, old_is_sold_out: bool, new_is_sold_out: bool) -> bool:
        """
        Determine if an availability change represents a sell out.

        A sell out occurs when is_sold_out transitions from False to True,
        meaning tickets that were previously available are now unavailable.

        Args:
            old_is_sold_out: Previous sold out status
            new_is_sold_out: Current sold out status

        Returns:
            True if this is a sell out (available -> sold out), False otherwise
        """
        return old_is_sold_out is False and new_is_sold_out is True

    async def check_and_alert_sold_out(
        self,
        event_uuid: str,
        previous_is_sold_out: bool,
        current_is_sold_out: bool,
        event_data: dict[str, Any] | None = None,
    ) -> SoldOutAlertResult:
        """
        Check for sell out and send alert if detected.

        This is the main entry point for sell out detection. Call this method
        whenever an event's availability is updated.

        Args:
            event_uuid: UUID of the event
            previous_is_sold_out: Previous sold out status (before update)
            current_is_sold_out: Current sold out status (after update)
            event_data: Optional dict with event details. If not provided,
                       will be fetched from database.

        Returns:
            SoldOutAlertResult with detection and notification details
        """
        result = SoldOutAlertResult(
            event_id=event_uuid,
            is_sold_out=False,
            alert_sent=False,
        )

        # Check if this is a sell out
        if not self.is_sell_out(previous_is_sold_out, current_is_sold_out):
            logger.debug(
                f"Event {event_uuid}: Not a sell out (sold_out: {previous_is_sold_out} -> {current_is_sold_out})"
            )
            return result

        result.is_sold_out = True
        logger.info(f"SOLD OUT DETECTED for event {event_uuid}!")

        # Get event data if not provided
        if event_data is None:
            event_data = await self._fetch_event_data(event_uuid)
            if event_data is None:
                result.error_message = f"Event {event_uuid} not found in database"
                logger.error(result.error_message)
                return result

        # Send sold out alert
        try:
            notification_result = await self._send_sold_out_alert(event_uuid, event_data)
            result.notification_result = notification_result
            result.alert_sent = notification_result.any_successful

            if result.alert_sent:
                logger.info(
                    f"Sold out alert sent for event {event_uuid}: "
                    f"{notification_result.successful_deliveries}/{notification_result.total_webhooks} webhooks"
                )
            else:
                logger.warning(
                    f"Sold out alert failed for event {event_uuid}: "
                    f"0/{notification_result.total_webhooks} webhooks succeeded"
                )

        except Exception as e:
            result.error_message = f"Failed to send sold out alert: {str(e)}"
            logger.exception(f"Error sending sold out alert for event {event_uuid}")

        return result

    async def process_availability_change(
        self,
        event_uuid: str,
        old_is_sold_out: bool,
        new_is_sold_out: bool,
        event_data: dict[str, Any] | None = None,
    ) -> SoldOutAlertResult:
        """
        Process an availability change and send sold out alert if applicable.

        This is an alias for check_and_alert_sold_out for API compatibility.

        Args:
            event_uuid: UUID of the event
            old_is_sold_out: Previous sold out status
            new_is_sold_out: Current sold out status
            event_data: Optional event details dict

        Returns:
            SoldOutAlertResult with detection and notification details
        """
        return await self.check_and_alert_sold_out(
            event_uuid=event_uuid,
            previous_is_sold_out=old_is_sold_out,
            current_is_sold_out=new_is_sold_out,
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

    async def _send_sold_out_alert(
        self,
        event_uuid: str,
        event_data: dict[str, Any],
    ) -> NotificationRoutingResult:
        """
        Send sold out alert to all configured webhooks.

        Args:
            event_uuid: UUID of the event
            event_data: Dict with event details

        Returns:
            NotificationRoutingResult with delivery details
        """
        # Build price info for notification (last known prices)
        prices = []
        if event_data.get('current_price_low'):
            price_entry = {'price': event_data['current_price_low'], 'currency': 'USD'}
            if (
                event_data.get('current_price_high')
                and event_data['current_price_high'] != event_data['current_price_low']
            ):
                price_entry['label'] = 'From'
            prices.append(price_entry)

        if event_data.get('current_price_high') and event_data[
            'current_price_high'
        ] != event_data.get('current_price_low'):
            prices.append(
                {
                    'price': event_data['current_price_high'],
                    'currency': 'USD',
                    'label': 'To',
                }
            )

        # Build event display name
        event_name = event_data.get('event_name') or 'Event'
        if event_data.get('artist'):
            event_name = f"{event_data['artist']} - {event_name}"

        # Build additional info with all available details
        additional_info = {
            'Status': 'SOLD OUT - Inventory gone',
        }

        if event_data.get('event_date'):
            date_str = event_data['event_date']
            if event_data.get('event_time'):
                date_str += f" at {event_data['event_time']}"
            additional_info['Date'] = date_str

        if event_data.get('artist') and event_data.get('event_name'):
            additional_info['Artist'] = event_data['artist']

        # Include last known price information
        if prices:
            if len(prices) == 1:
                additional_info['Last Known Price'] = f"${prices[0]['price']:.2f}"
            else:
                additional_info['Last Known Price'] = (
                    f"${prices[0]['price']:.2f} - ${prices[1]['price']:.2f}"
                )

        # Send notification via router (handles all tag webhooks)
        result = await self.router.send_event_notification(
            event_uuid=event_uuid,
            notification_type='sold_out',  # Logged as 'sold_out' type
            event_name=event_name,
            venue=event_data.get('venue'),
            prices=prices,
            url=event_data.get('url'),
            availability='out_of_stock',  # Sold out means unavailable
            additional_info=additional_info,
        )

        return result


# =============================================================================
# Convenience Functions
# =============================================================================


async def send_sold_out_alert(
    store,
    event_uuid: str,
    event_data: dict[str, Any] | None = None,
    default_webhook_url: str | None = None,
) -> SoldOutAlertResult:
    """
    Convenience function to send a sold out alert.

    This function creates a SoldOutAlertService and sends the alert immediately.
    Use this for one-off sold out notifications.

    Args:
        store: PostgreSQLStore instance
        event_uuid: UUID of the event
        event_data: Optional dict with event details
        default_webhook_url: Fallback webhook URL

    Returns:
        SoldOutAlertResult with delivery details

    Example:
        result = await send_sold_out_alert(
            store=store,
            event_uuid="abc-123",
            event_data={
                'event_name': 'Taylor Swift - Eras Tour',
                'venue': 'United Center',
                'current_price_low': 150.00,
                'url': 'https://tickets.example.com/...'
            }
        )
        if result.success:
            print("Sold out alert sent!")
    """
    service = SoldOutAlertService(
        store=store,
        default_webhook_url=default_webhook_url,
    )

    # For convenience function, assume this is definitely a sell out
    return await service.check_and_alert_sold_out(
        event_uuid=event_uuid,
        previous_is_sold_out=False,
        current_is_sold_out=True,
        event_data=event_data,
    )


async def check_availability_change_for_sold_out(
    store,
    event_uuid: str,
    old_is_sold_out: bool,
    new_is_sold_out: bool,
    event_data: dict[str, Any] | None = None,
    default_webhook_url: str | None = None,
) -> SoldOutAlertResult:
    """
    Check an availability change and send sold out alert if applicable.

    This is the recommended entry point for integrating sold out alerts
    into your monitoring flow. Call this whenever availability changes.

    Args:
        store: PostgreSQLStore instance
        event_uuid: UUID of the event
        old_is_sold_out: Previous sold out status
        new_is_sold_out: Current sold out status
        event_data: Optional dict with event details
        default_webhook_url: Fallback webhook URL

    Returns:
        SoldOutAlertResult (is_sold_out=False if not a sell out)

    Example:
        # In your update worker:
        changes = await event.update_event_data(session, is_sold_out=new_status)

        if changes['availability_changed']:
            result = await check_availability_change_for_sold_out(
                store=store,
                event_uuid=str(event.id),
                old_is_sold_out=old_status,
                new_is_sold_out=new_status,
            )
            if result.is_sold_out:
                logger.info(f"Sold out alert sent: {result.alert_sent}")
    """
    service = SoldOutAlertService(
        store=store,
        default_webhook_url=default_webhook_url,
    )

    return await service.process_availability_change(
        event_uuid=event_uuid,
        old_is_sold_out=old_is_sold_out,
        new_is_sold_out=new_is_sold_out,
        event_data=event_data,
    )


# =============================================================================
# CLI Testing
# =============================================================================

if __name__ == '__main__':
    import asyncio
    import os

    async def test_sold_out_alert():
        """Test the sold out alert service."""
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
            service = SoldOutAlertService(
                store=store,
                default_webhook_url=default_webhook,
            )

            # Test sell out detection logic
            print('\n--- Testing Sell Out Detection ---')
            test_cases = [
                (False, True, True, 'available -> sold out (SELL OUT)'),
                (True, False, False, 'sold out -> available (not sell out - it\'s a restock)'),
                (True, True, False, 'sold out -> sold out (no change)'),
                (False, False, False, 'available -> available (no change)'),
            ]

            for old_status, new_status, expected, desc in test_cases:
                is_sell_out = service.is_sell_out(old_status, new_status)
                status = 'PASS' if is_sell_out == expected else 'FAIL'
                print(f'  [{status}] {desc}: is_sell_out={is_sell_out}')

            # Get a test event
            watches = await store.get_all_watches()
            if not watches:
                print('\nNo watches in database to test with')
                return

            event_uuid = list(watches.keys())[0]
            watch = watches[event_uuid]

            print('\n--- Testing Sold Out Alert for Event ---')
            print(f'Event: {watch.get("title") or watch.get("url")}')

            # Simulate a sold out alert
            result = await service.check_and_alert_sold_out(
                event_uuid=event_uuid,
                previous_is_sold_out=False,
                current_is_sold_out=True,
            )

            print('\nSold Out Alert Result:')
            print(f'  Is sold out: {result.is_sold_out}')
            print(f'  Alert sent: {result.alert_sent}')

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

    asyncio.run(test_sold_out_alert())
