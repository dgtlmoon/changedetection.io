"""
Instant Restock Alert Service for TicketWatch/ATC Page Monitor

This module provides instant high-priority Slack alerts when a sold-out event
gets tickets available again. Designed for arbitrage scenarios where speed
is critical.

Features:
- Detects is_sold_out transition from true to false (restock detection)
- Sends immediate high-priority notifications (no batching/delay)
- Uses distinct 'RESTOCK ALERT' message template
- Includes all event details: name, artist, venue, date, time, price, link
- Routes alerts to all tag webhooks for the event
- Logs all restock alerts with type='restock' in notification_log

Usage:
    from tasks.restock_alert import RestockAlertService
    from tasks.postgresql_store import PostgreSQLStore

    store = PostgreSQLStore(database_url=os.getenv('DATABASE_URL'))
    await store.initialize()

    service = RestockAlertService(store=store, default_webhook_url=os.getenv('DEFAULT_SLACK_WEBHOOK'))

    # Check for restock and send alert if detected
    result = await service.check_and_alert_restock(
        event_uuid="...",
        previous_is_sold_out=True,
        current_is_sold_out=False
    )

    # Or process availability change directly
    result = await service.process_availability_change(
        event_uuid="...",
        old_is_sold_out=True,
        new_is_sold_out=False,
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
class RestockAlertResult:
    """Result of a restock alert check and notification."""

    event_id: str
    is_restock: bool
    alert_sent: bool
    notification_result: NotificationRoutingResult | None = None
    error_message: str | None = None

    @property
    def success(self) -> bool:
        """Check if restock was detected and alert was successfully sent."""
        return self.is_restock and self.alert_sent

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/debugging."""
        return {
            'event_id': self.event_id,
            'is_restock': self.is_restock,
            'alert_sent': self.alert_sent,
            'notification_result': self.notification_result.to_dict()
            if self.notification_result
            else None,
            'error_message': self.error_message,
        }


# =============================================================================
# Restock Alert Service
# =============================================================================


class RestockAlertService:
    """
    Service for detecting restocks and sending instant high-priority alerts.

    This service is designed for time-sensitive arbitrage scenarios where
    immediate notification of restocked tickets is critical.

    Key features:
    - Instant delivery (no batching or delays)
    - High-priority message formatting with 'RESTOCK ALERT' header
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
        Initialize the restock alert service.

        Args:
            store: PostgreSQLStore instance (must be initialized)
            default_webhook_url: Fallback Slack webhook URL when no tag webhooks exist
        """
        self.store = store
        self.default_webhook_url = default_webhook_url
        self.router = TagNotificationRouter(
            store=store,
            default_webhook_url=default_webhook_url,
            use_blocks=True,  # Rich formatting for high visibility
        )

    def is_restock(self, old_is_sold_out: bool, new_is_sold_out: bool) -> bool:
        """
        Determine if an availability change represents a restock.

        A restock occurs when is_sold_out transitions from True to False,
        meaning tickets that were previously unavailable are now available.

        Args:
            old_is_sold_out: Previous sold out status
            new_is_sold_out: Current sold out status

        Returns:
            True if this is a restock (sold out -> available), False otherwise
        """
        return old_is_sold_out is True and new_is_sold_out is False

    async def check_and_alert_restock(
        self,
        event_uuid: str,
        previous_is_sold_out: bool,
        current_is_sold_out: bool,
        event_data: dict[str, Any] | None = None,
    ) -> RestockAlertResult:
        """
        Check for restock and send instant alert if detected.

        This is the main entry point for restock detection. Call this method
        whenever an event's availability is updated.

        Args:
            event_uuid: UUID of the event
            previous_is_sold_out: Previous sold out status (before update)
            current_is_sold_out: Current sold out status (after update)
            event_data: Optional dict with event details. If not provided,
                       will be fetched from database.

        Returns:
            RestockAlertResult with detection and notification details
        """
        result = RestockAlertResult(
            event_id=event_uuid,
            is_restock=False,
            alert_sent=False,
        )

        # Check if this is a restock
        if not self.is_restock(previous_is_sold_out, current_is_sold_out):
            logger.debug(
                f"Event {event_uuid}: Not a restock (sold_out: {previous_is_sold_out} -> {current_is_sold_out})"
            )
            return result

        result.is_restock = True
        logger.info(f"RESTOCK DETECTED for event {event_uuid}!")

        # Get event data if not provided
        if event_data is None:
            event_data = await self._fetch_event_data(event_uuid)
            if event_data is None:
                result.error_message = f"Event {event_uuid} not found in database"
                logger.error(result.error_message)
                return result

        # Send instant high-priority alert
        try:
            notification_result = await self._send_restock_alert(event_uuid, event_data)
            result.notification_result = notification_result
            result.alert_sent = notification_result.any_successful

            if result.alert_sent:
                logger.info(
                    f"Restock alert sent for event {event_uuid}: "
                    f"{notification_result.successful_deliveries}/{notification_result.total_webhooks} webhooks"
                )
            else:
                logger.warning(
                    f"Restock alert failed for event {event_uuid}: "
                    f"0/{notification_result.total_webhooks} webhooks succeeded"
                )

        except Exception as e:
            result.error_message = f"Failed to send restock alert: {str(e)}"
            logger.exception(f"Error sending restock alert for event {event_uuid}")

        return result

    async def process_availability_change(
        self,
        event_uuid: str,
        old_is_sold_out: bool,
        new_is_sold_out: bool,
        event_data: dict[str, Any] | None = None,
    ) -> RestockAlertResult:
        """
        Process an availability change and send restock alert if applicable.

        This is an alias for check_and_alert_restock for API compatibility.

        Args:
            event_uuid: UUID of the event
            old_is_sold_out: Previous sold out status
            new_is_sold_out: Current sold out status
            event_data: Optional event details dict

        Returns:
            RestockAlertResult with detection and notification details
        """
        return await self.check_and_alert_restock(
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

    async def _send_restock_alert(
        self,
        event_uuid: str,
        event_data: dict[str, Any],
    ) -> NotificationRoutingResult:
        """
        Send instant restock alert to all configured webhooks.

        This method sends the alert immediately with no batching or delay.
        The alert uses a distinct 'RESTOCK ALERT' header for high visibility.

        Args:
            event_uuid: UUID of the event
            event_data: Dict with event details

        Returns:
            NotificationRoutingResult with delivery details
        """
        # Build price info for notification
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
            'Priority': 'HIGH - ACT NOW!',
        }

        if event_data.get('event_date'):
            date_str = event_data['event_date']
            if event_data.get('event_time'):
                date_str += f" at {event_data['event_time']}"
            additional_info['Date'] = date_str

        if event_data.get('artist') and event_data.get('event_name'):
            additional_info['Artist'] = event_data['artist']

        # Send notification via router (handles all tag webhooks)
        result = await self.router.send_event_notification(
            event_uuid=event_uuid,
            notification_type='restock',  # Logged as 'restock' type
            event_name=event_name,
            venue=event_data.get('venue'),
            prices=prices,
            url=event_data.get('url'),
            availability='in_stock',  # Restock means now available
            additional_info=additional_info,
        )

        return result


# =============================================================================
# Convenience Functions
# =============================================================================


async def send_restock_alert(
    store,
    event_uuid: str,
    event_data: dict[str, Any] | None = None,
    default_webhook_url: str | None = None,
) -> RestockAlertResult:
    """
    Convenience function to send an instant restock alert.

    This function creates a RestockAlertService and sends the alert immediately.
    Use this for one-off restock notifications.

    Args:
        store: PostgreSQLStore instance
        event_uuid: UUID of the event
        event_data: Optional dict with event details
        default_webhook_url: Fallback webhook URL

    Returns:
        RestockAlertResult with delivery details

    Example:
        result = await send_restock_alert(
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
            print("Restock alert sent!")
    """
    service = RestockAlertService(
        store=store,
        default_webhook_url=default_webhook_url,
    )

    # For convenience function, assume this is definitely a restock
    return await service.check_and_alert_restock(
        event_uuid=event_uuid,
        previous_is_sold_out=True,
        current_is_sold_out=False,
        event_data=event_data,
    )


async def check_availability_change_for_restock(
    store,
    event_uuid: str,
    old_is_sold_out: bool,
    new_is_sold_out: bool,
    event_data: dict[str, Any] | None = None,
    default_webhook_url: str | None = None,
) -> RestockAlertResult:
    """
    Check an availability change and send restock alert if applicable.

    This is the recommended entry point for integrating restock alerts
    into your monitoring flow. Call this whenever availability changes.

    Args:
        store: PostgreSQLStore instance
        event_uuid: UUID of the event
        old_is_sold_out: Previous sold out status
        new_is_sold_out: Current sold out status
        event_data: Optional dict with event details
        default_webhook_url: Fallback webhook URL

    Returns:
        RestockAlertResult (is_restock=False if not a restock)

    Example:
        # In your update worker:
        changes = await event.update_event_data(session, is_sold_out=new_status)

        if changes['availability_changed']:
            result = await check_availability_change_for_restock(
                store=store,
                event_uuid=str(event.id),
                old_is_sold_out=old_status,
                new_is_sold_out=new_status,
            )
            if result.is_restock:
                logger.info(f"Restock alert sent: {result.alert_sent}")
    """
    service = RestockAlertService(
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

    async def test_restock_alert():
        """Test the restock alert service."""
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
            service = RestockAlertService(
                store=store,
                default_webhook_url=default_webhook,
            )

            # Test restock detection logic
            print('\n--- Testing Restock Detection ---')
            test_cases = [
                (True, False, True, 'sold out -> available (RESTOCK)'),
                (False, True, False, 'available -> sold out (not restock)'),
                (True, True, False, 'sold out -> sold out (no change)'),
                (False, False, False, 'available -> available (no change)'),
            ]

            for old_status, new_status, expected, desc in test_cases:
                is_restock = service.is_restock(old_status, new_status)
                status = 'PASS' if is_restock == expected else 'FAIL'
                print(f'  [{status}] {desc}: is_restock={is_restock}')

            # Get a test event
            watches = await store.get_all_watches()
            if not watches:
                print('\nNo watches in database to test with')
                return

            event_uuid = list(watches.keys())[0]
            watch = watches[event_uuid]

            print('\n--- Testing Restock Alert for Event ---')
            print(f'Event: {watch.get("title") or watch.get("url")}')

            # Simulate a restock alert
            result = await service.check_and_alert_restock(
                event_uuid=event_uuid,
                previous_is_sold_out=True,
                current_is_sold_out=False,
            )

            print('\nRestock Alert Result:')
            print(f'  Is restock: {result.is_restock}')
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

    asyncio.run(test_restock_alert())
