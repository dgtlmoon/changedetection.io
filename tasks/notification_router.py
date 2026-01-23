"""
Tag-Based Notification Router for TicketWatch/ATC Page Monitor

This module provides notification routing based on event tags. When an event
triggers a notification (price change, restock, etc.), the router:
1. Looks up the event's tags
2. Sends notifications to each tag's webhook URL (if configured and not muted)
3. Falls back to a default webhook if no tag webhooks are available
4. Logs all notification attempts to the database

Usage:
    from tasks.notification_router import TagNotificationRouter
    from tasks.postgresql_store import PostgreSQLStore

    store = PostgreSQLStore(database_url=os.getenv('DATABASE_URL'))
    await store.initialize()

    router = TagNotificationRouter(store=store, default_webhook_url=os.getenv('DEFAULT_SLACK_WEBHOOK'))
    result = await router.send_event_notification(
        event_uuid="...",
        notification_type="restock",
        message_builder=some_message_builder
    )
"""

import uuid as uuid_builder
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import requests

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

from tasks.models import (
    NotificationLog,
)
from tasks.notification import TicketAlertMessage

# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class WebhookDeliveryResult:
    """Result of a single webhook delivery attempt."""

    webhook_url: str
    tag_id: str | None
    tag_name: str | None
    success: bool
    response_status: int | None = None
    response_body: str | None = None
    error_message: str | None = None


@dataclass
class NotificationRoutingResult:
    """Result of routing a notification to all applicable webhooks."""

    event_id: str
    notification_type: str
    total_webhooks: int = 0
    successful_deliveries: int = 0
    failed_deliveries: int = 0
    skipped_muted: int = 0
    used_default_fallback: bool = False
    deliveries: list[WebhookDeliveryResult] = field(default_factory=list)

    @property
    def all_successful(self) -> bool:
        """Check if all deliveries were successful."""
        return self.successful_deliveries == self.total_webhooks and self.total_webhooks > 0

    @property
    def any_successful(self) -> bool:
        """Check if at least one delivery was successful."""
        return self.successful_deliveries > 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/debugging."""
        return {
            'event_id': self.event_id,
            'notification_type': self.notification_type,
            'total_webhooks': self.total_webhooks,
            'successful_deliveries': self.successful_deliveries,
            'failed_deliveries': self.failed_deliveries,
            'skipped_muted': self.skipped_muted,
            'used_default_fallback': self.used_default_fallback,
            'deliveries': [
                {
                    'webhook_url': d.webhook_url[:50] + '...'
                    if len(d.webhook_url) > 50
                    else d.webhook_url,
                    'tag_name': d.tag_name,
                    'success': d.success,
                    'error': d.error_message,
                }
                for d in self.deliveries
            ],
        }


# =============================================================================
# Tag Notification Router
# =============================================================================


class TagNotificationRouter:
    """
    Routes notifications to Slack webhooks based on event tags.

    The router implements the following logic:
    1. Look up all tags associated with the event
    2. For each tag with a slack_webhook_url and notification_muted=False:
       - Send notification to that webhook
       - Log the result
    3. If no tag webhooks are available/successful, use the default webhook
    4. Log all delivery attempts to NotificationLog

    Attributes:
        store: PostgreSQLStore instance for database access
        default_webhook_url: Fallback webhook URL when no tag webhooks are configured
        use_blocks: Whether to use Slack Block Kit formatting
    """

    def __init__(
        self,
        store,
        default_webhook_url: str | None = None,
        use_blocks: bool = True,
    ):
        """
        Initialize the notification router.

        Args:
            store: PostgreSQLStore instance (must be initialized)
            default_webhook_url: Fallback Slack webhook URL when no tag webhooks exist
            use_blocks: Whether to use Slack Block Kit formatting (default True)
        """
        self.store = store
        self.default_webhook_url = default_webhook_url
        self.use_blocks = use_blocks

    async def send_event_notification(
        self,
        event_uuid: str,
        notification_type: str,
        event_name: str | None = None,
        venue: str | None = None,
        prices: list[dict[str, Any]] | None = None,
        old_prices: list[dict[str, Any]] | None = None,
        url: str | None = None,
        availability: str | None = None,
        additional_info: dict[str, str] | None = None,
    ) -> NotificationRoutingResult:
        """
        Send a notification to all applicable webhooks for an event.

        This is the main entry point for sending notifications. It:
        1. Fetches webhooks from event's tags (excluding muted tags)
        2. Sends to each webhook
        3. Falls back to default webhook if no tag webhooks
        4. Logs all attempts

        Args:
            event_uuid: UUID of the event triggering the notification
            notification_type: Type of notification (restock, price_change, etc.)
            event_name: Name of the event
            venue: Venue name
            prices: Current price list
            old_prices: Previous prices (for price change notifications)
            url: Event/ticket URL
            availability: Availability status
            additional_info: Extra information to include

        Returns:
            NotificationRoutingResult with delivery details
        """
        result = NotificationRoutingResult(
            event_id=event_uuid,
            notification_type=notification_type,
        )

        # Get webhooks for event's tags
        webhooks = await self.store.get_webhooks_for_event(event_uuid)

        # Track muted tags (webhooks list already excludes muted)
        # Get all tags to count muted ones
        all_tags = await self._get_all_event_tags(event_uuid)
        muted_count = sum(1 for t in all_tags if t.get('notification_muted', False))
        result.skipped_muted = muted_count

        logger.debug(
            f"Event {event_uuid}: found {len(webhooks)} active webhooks, {muted_count} muted tags"
        )

        # If no tag webhooks, try default
        if not webhooks:
            if self.default_webhook_url:
                logger.info(f"No tag webhooks for event {event_uuid}, using default webhook")
                result.used_default_fallback = True
                webhooks = [
                    {
                        'tag_id': None,
                        'tag_name': 'default',
                        'webhook_url': self.default_webhook_url,
                    }
                ]
            else:
                logger.warning(
                    f"No webhooks available for event {event_uuid} (no tag webhooks, no default)"
                )
                return result

        result.total_webhooks = len(webhooks)

        # Send to each webhook
        for webhook_info in webhooks:
            delivery_result = await self._send_to_webhook(
                webhook_info=webhook_info,
                event_uuid=event_uuid,
                notification_type=notification_type,
                event_name=event_name,
                venue=venue,
                prices=prices,
                old_prices=old_prices,
                url=url,
                availability=availability,
                additional_info=additional_info,
            )

            result.deliveries.append(delivery_result)

            if delivery_result.success:
                result.successful_deliveries += 1
            else:
                result.failed_deliveries += 1

        logger.info(
            f"Notification routing complete for event {event_uuid}: "
            f"{result.successful_deliveries}/{result.total_webhooks} successful"
        )

        return result

    async def _send_to_webhook(
        self,
        webhook_info: dict[str, Any],
        event_uuid: str,
        notification_type: str,
        event_name: str | None = None,
        venue: str | None = None,
        prices: list[dict[str, Any]] | None = None,
        old_prices: list[dict[str, Any]] | None = None,
        url: str | None = None,
        availability: str | None = None,
        additional_info: dict[str, str] | None = None,
    ) -> WebhookDeliveryResult:
        """
        Send a notification to a single webhook and log the result.

        Args:
            webhook_info: Dict with tag_id, tag_name, webhook_url
            event_uuid: Event UUID
            notification_type: Type of notification
            event_name: Event name
            venue: Venue name
            prices: Current prices
            old_prices: Previous prices
            url: Event URL
            availability: Availability status
            additional_info: Additional info

        Returns:
            WebhookDeliveryResult with delivery outcome
        """
        webhook_url = webhook_info['webhook_url']
        tag_id = webhook_info.get('tag_id')
        tag_name = webhook_info.get('tag_name')

        # Build the message
        builder = TicketAlertMessage()
        builder.set_event(event_name or 'Event Update', venue)
        builder.set_prices(prices or [], old_prices)
        if url:
            builder.set_url(url)
        if availability:
            builder.set_availability(availability)
        builder.set_change_type(notification_type)

        if additional_info:
            for key, value in additional_info.items():
                builder.add_info(key, value)

        # Add tag info to message
        if tag_name and tag_name != 'default':
            builder.add_info('Tag', tag_name)

        # Build payload
        if self.use_blocks:
            payload = {'blocks': builder.build_blocks()}
        else:
            payload = {'text': builder.build_text()}

        # Send the webhook
        delivery_result = WebhookDeliveryResult(
            webhook_url=webhook_url,
            tag_id=tag_id,
            tag_name=tag_name,
            success=False,
        )

        try:
            response = requests.post(
                webhook_url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=30,
            )

            delivery_result.response_status = response.status_code
            delivery_result.response_body = response.text[:500] if response.text else None

            if response.status_code == 200:
                delivery_result.success = True
                logger.debug(f"Webhook delivery successful to {tag_name or 'default'}")
            else:
                delivery_result.error_message = (
                    f"HTTP {response.status_code}: {response.text[:100]}"
                )
                logger.error(
                    f"Webhook delivery failed to {tag_name or 'default'}: "
                    f"HTTP {response.status_code}"
                )

        except requests.exceptions.Timeout:
            delivery_result.error_message = 'Request timeout (30s)'
            logger.error(f"Webhook timeout for {tag_name or 'default'}")

        except requests.exceptions.RequestException as e:
            delivery_result.error_message = str(e)[:200]
            logger.error(f"Webhook request failed for {tag_name or 'default'}: {e}")

        except Exception as e:
            delivery_result.error_message = f"Unexpected error: {str(e)[:200]}"
            logger.exception(f"Unexpected webhook error for {tag_name or 'default'}")

        # Log to database
        await self._log_notification(
            event_uuid=event_uuid,
            tag_id=tag_id,
            notification_type=notification_type,
            webhook_url=webhook_url,
            payload=payload,
            delivery_result=delivery_result,
        )

        return delivery_result

    async def _log_notification(
        self,
        event_uuid: str,
        tag_id: str | None,
        notification_type: str,
        webhook_url: str,
        payload: dict[str, Any],
        delivery_result: WebhookDeliveryResult,
    ) -> None:
        """
        Log a notification delivery attempt to the database.

        Args:
            event_uuid: Event UUID
            tag_id: Tag UUID (if applicable)
            notification_type: Type of notification
            webhook_url: Webhook URL used
            payload: Payload sent
            delivery_result: Result of the delivery
        """
        try:
            async with self.store.session() as session:
                # Convert UUIDs
                event_id = uuid_builder.UUID(event_uuid) if event_uuid else None
                tag_uuid = uuid_builder.UUID(tag_id) if tag_id else None

                # Create log entry
                await NotificationLog.log_notification(
                    session=session,
                    notification_type=notification_type,
                    event_id=event_id,
                    tag_id=tag_uuid,
                    webhook_url=webhook_url,
                    payload=payload,
                    response_status=delivery_result.response_status,
                    response_body=delivery_result.response_body,
                    success=delivery_result.success,
                    error_message=delivery_result.error_message,
                    metadata={
                        'tag_name': delivery_result.tag_name,
                        'timestamp': datetime.now().isoformat(),
                    },
                )

        except Exception as e:
            logger.error(f"Failed to log notification: {e}")

    async def _get_all_event_tags(self, event_uuid: str) -> list[dict[str, Any]]:
        """
        Get all tags for an event (including muted ones).

        Args:
            event_uuid: Event UUID

        Returns:
            List of tag dictionaries
        """
        tags = await self.store.get_all_tags_for_watch(event_uuid)
        return list(tags.values())

    async def send_test_notification(
        self,
        webhook_url: str,
        tag_name: str | None = None,
    ) -> WebhookDeliveryResult:
        """
        Send a test notification to verify webhook configuration.

        Args:
            webhook_url: Webhook URL to test
            tag_name: Optional tag name for the test message

        Returns:
            WebhookDeliveryResult with test outcome
        """
        builder = TicketAlertMessage()
        builder.set_event('Test Notification', None)
        builder.set_change_type('update')
        builder.add_info('Status', 'Webhook configuration verified')
        if tag_name:
            builder.add_info('Tag', tag_name)

        if self.use_blocks:
            payload = {'blocks': builder.build_blocks()}
        else:
            payload = {'text': builder.build_text()}

        result = WebhookDeliveryResult(
            webhook_url=webhook_url,
            tag_id=None,
            tag_name=tag_name,
            success=False,
        )

        try:
            response = requests.post(
                webhook_url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=30,
            )

            result.response_status = response.status_code
            result.response_body = response.text[:500] if response.text else None

            if response.status_code == 200:
                result.success = True
                logger.info(f"Test webhook successful for {tag_name or 'webhook'}")
            else:
                result.error_message = f"HTTP {response.status_code}: {response.text[:100]}"

        except requests.exceptions.Timeout:
            result.error_message = 'Request timeout (30s)'
        except requests.exceptions.RequestException as e:
            result.error_message = str(e)[:200]
        except Exception as e:
            result.error_message = f"Unexpected error: {str(e)[:200]}"

        return result


# =============================================================================
# Convenience Functions
# =============================================================================


async def send_notification_for_event(
    store,
    event_uuid: str,
    notification_type: str,
    default_webhook_url: str | None = None,
    **kwargs,
) -> NotificationRoutingResult:
    """
    Convenience function to send a notification for an event.

    Args:
        store: PostgreSQLStore instance
        event_uuid: Event UUID
        notification_type: Type of notification
        default_webhook_url: Fallback webhook URL
        **kwargs: Additional arguments passed to send_event_notification

    Returns:
        NotificationRoutingResult
    """
    router = TagNotificationRouter(
        store=store,
        default_webhook_url=default_webhook_url,
    )
    return await router.send_event_notification(
        event_uuid=event_uuid,
        notification_type=notification_type,
        **kwargs,
    )


async def get_notification_logs_for_event(
    store,
    event_uuid: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """
    Get notification logs for an event.

    Args:
        store: PostgreSQLStore instance
        event_uuid: Event UUID
        limit: Maximum number of logs to return

    Returns:
        List of notification log dictionaries
    """
    async with store.session() as session:
        event_id = uuid_builder.UUID(event_uuid)
        logs = await NotificationLog.get_logs_for_event(session, event_id, limit)
        return [log.to_dict() for log in logs]


# =============================================================================
# CLI Testing
# =============================================================================

if __name__ == '__main__':
    import asyncio
    import os

    async def test_router():
        """Test the notification router."""
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
            router = TagNotificationRouter(
                store=store,
                default_webhook_url=default_webhook,
            )

            # Get a test event
            watches = await store.get_all_watches()
            if not watches:
                print('No watches in database to test with')
                return

            event_uuid = list(watches.keys())[0]
            watch = watches[event_uuid]

            print(f'Testing notification for event: {watch.get("title") or watch.get("url")}')

            # Send test notification
            result = await router.send_event_notification(
                event_uuid=event_uuid,
                notification_type='restock',
                event_name=watch.get('title', 'Test Event'),
                url=watch.get('url'),
                availability='in_stock',
            )

            print('\nRouting result:')
            print(f'  Total webhooks: {result.total_webhooks}')
            print(f'  Successful: {result.successful_deliveries}')
            print(f'  Failed: {result.failed_deliveries}')
            print(f'  Skipped (muted): {result.skipped_muted}')
            print(f'  Used default: {result.used_default_fallback}')

            for delivery in result.deliveries:
                status = 'OK' if delivery.success else 'FAILED'
                print(f'  - {delivery.tag_name}: {status}')
                if delivery.error_message:
                    print(f'    Error: {delivery.error_message}')

            # Get notification logs
            print('\nRecent notification logs:')
            logs = await get_notification_logs_for_event(store, event_uuid, limit=5)
            for log in logs:
                print(f"  - {log['notification_type']}: {'OK' if log['success'] else 'FAILED'}")
                print(f"    Sent at: {log['sent_at']}")

        finally:
            await store.close()

    asyncio.run(test_router())
