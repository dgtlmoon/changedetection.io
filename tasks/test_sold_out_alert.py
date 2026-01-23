"""
Unit tests for the Sold Out Alert Service.

Tests cover:
- Sell out detection logic (is_sold_out: False -> True)
- Non-sell-out scenarios (availability changes that aren't sell outs)
- Notification delivery
- Message formatting with 'Sold Out' indicator
- All event details inclusion (name, artist, venue, date, time, last known price, link)
- Tag webhook routing
- Notification logging with type='sold_out'
- Error handling and edge cases

Run with: pytest tasks/test_sold_out_alert.py -v
"""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tasks.sold_out_alert import (
    SoldOutAlertResult,
    SoldOutAlertService,
    check_availability_change_for_sold_out,
    send_sold_out_alert,
)

# Configure pytest-anyio for async tests
pytestmark = pytest.mark.anyio


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_store():
    """Create a mock PostgreSQLStore."""
    store = MagicMock()
    store.session = MagicMock()

    # Create async context manager mock
    async_session = AsyncMock()
    async_session.__aenter__ = AsyncMock(return_value=async_session)
    async_session.__aexit__ = AsyncMock(return_value=None)
    store.session.return_value = async_session

    return store


@pytest.fixture
def service(mock_store):
    """Create a SoldOutAlertService with mock store."""
    return SoldOutAlertService(
        store=mock_store,
        default_webhook_url='https://hooks.slack.com/default',
    )


@pytest.fixture
def sample_event_uuid():
    """Return a sample event UUID."""
    return str(uuid.uuid4())


@pytest.fixture
def sample_event_data():
    """Return sample event data for testing."""
    return {
        'event_name': 'Eras Tour',
        'artist': 'Taylor Swift',
        'venue': 'United Center',
        'event_date': '2025-06-15',
        'event_time': '19:30:00',
        'current_price_low': 150.00,
        'current_price_high': 450.00,
        'url': 'https://tickets.example.com/taylor-swift-eras-tour',
        'is_sold_out': True,
    }


@pytest.fixture
def sample_webhooks():
    """Return sample webhook configurations."""
    return [
        {
            'tag_id': str(uuid.uuid4()),
            'tag_name': 'concerts',
            'webhook_url': 'https://hooks.slack.com/services/T123/B456/abc123',
        },
        {
            'tag_id': str(uuid.uuid4()),
            'tag_name': 'high-value',
            'webhook_url': 'https://hooks.slack.com/services/T123/B789/def456',
        },
    ]


# =============================================================================
# SoldOutAlertResult Tests
# =============================================================================


class TestSoldOutAlertResult:
    """Tests for SoldOutAlertResult dataclass."""

    def test_successful_sold_out_alert(self):
        """Test result for successful sold out alert."""
        from tasks.notification_router import NotificationRoutingResult

        notification_result = NotificationRoutingResult(
            event_id='123',
            notification_type='sold_out',
            total_webhooks=2,
            successful_deliveries=2,
            failed_deliveries=0,
        )

        result = SoldOutAlertResult(
            event_id='123',
            is_sold_out=True,
            alert_sent=True,
            notification_result=notification_result,
        )

        assert result.success is True
        assert result.is_sold_out is True
        assert result.alert_sent is True
        assert result.error_message is None

    def test_sold_out_detected_but_alert_failed(self):
        """Test result when sold out detected but alert failed."""
        result = SoldOutAlertResult(
            event_id='123',
            is_sold_out=True,
            alert_sent=False,
            error_message='Failed to send alert',
        )

        assert result.success is False
        assert result.is_sold_out is True
        assert result.alert_sent is False

    def test_not_a_sell_out(self):
        """Test result when change is not a sell out."""
        result = SoldOutAlertResult(
            event_id='123',
            is_sold_out=False,
            alert_sent=False,
        )

        assert result.success is False
        assert result.is_sold_out is False
        assert result.alert_sent is False

    def test_to_dict(self):
        """Test to_dict method."""
        result = SoldOutAlertResult(
            event_id='abc-123',
            is_sold_out=True,
            alert_sent=True,
        )

        d = result.to_dict()
        assert d['event_id'] == 'abc-123'
        assert d['is_sold_out'] is True
        assert d['alert_sent'] is True
        assert d['notification_result'] is None


# =============================================================================
# Sell Out Detection Logic Tests
# =============================================================================


class TestSellOutDetection:
    """Tests for the sell out detection logic."""

    def test_is_sell_out_false_to_true(self, service):
        """Test that sold_out False -> True is detected as sell out."""
        assert service.is_sell_out(old_is_sold_out=False, new_is_sold_out=True) is True

    def test_is_not_sell_out_true_to_false(self, service):
        """Test that sold_out True -> False is NOT a sell out (it's a restock)."""
        assert service.is_sell_out(old_is_sold_out=True, new_is_sold_out=False) is False

    def test_is_not_sell_out_true_to_true(self, service):
        """Test that sold_out True -> True is NOT a sell out (no change)."""
        assert service.is_sell_out(old_is_sold_out=True, new_is_sold_out=True) is False

    def test_is_not_sell_out_false_to_false(self, service):
        """Test that sold_out False -> False is NOT a sell out (no change)."""
        assert service.is_sell_out(old_is_sold_out=False, new_is_sold_out=False) is False


# =============================================================================
# Alert Sending Tests
# =============================================================================


class TestAlertSending:
    """Tests for the alert sending functionality."""

    @patch('tasks.sold_out_alert.TagNotificationRouter.send_event_notification')
    async def test_sends_alert_on_sell_out(
        self, mock_send, service, sample_event_uuid, sample_event_data
    ):
        """Test that alert is sent when sell out is detected."""
        from tasks.notification_router import NotificationRoutingResult

        mock_send.return_value = NotificationRoutingResult(
            event_id=sample_event_uuid,
            notification_type='sold_out',
            total_webhooks=1,
            successful_deliveries=1,
            failed_deliveries=0,
        )

        result = await service.check_and_alert_sold_out(
            event_uuid=sample_event_uuid,
            previous_is_sold_out=False,
            current_is_sold_out=True,
            event_data=sample_event_data,
        )

        assert result.is_sold_out is True
        assert result.alert_sent is True
        mock_send.assert_called_once()

    async def test_no_alert_when_not_sell_out(self, service, sample_event_uuid, sample_event_data):
        """Test that no alert is sent when change is not a sell out."""
        result = await service.check_and_alert_sold_out(
            event_uuid=sample_event_uuid,
            previous_is_sold_out=True,
            current_is_sold_out=False,  # This is a restock, not sell out
            event_data=sample_event_data,
        )

        assert result.is_sold_out is False
        assert result.alert_sent is False
        assert result.notification_result is None

    @patch('tasks.sold_out_alert.TagNotificationRouter.send_event_notification')
    async def test_notification_type_is_sold_out(
        self, mock_send, service, sample_event_uuid, sample_event_data
    ):
        """Test that notification type is 'sold_out' for logging."""
        from tasks.notification_router import NotificationRoutingResult

        mock_send.return_value = NotificationRoutingResult(
            event_id=sample_event_uuid,
            notification_type='sold_out',
            total_webhooks=1,
            successful_deliveries=1,
        )

        await service.check_and_alert_sold_out(
            event_uuid=sample_event_uuid,
            previous_is_sold_out=False,
            current_is_sold_out=True,
            event_data=sample_event_data,
        )

        # Verify notification_type='sold_out' was passed
        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs['notification_type'] == 'sold_out'


# =============================================================================
# Message Content Tests
# =============================================================================


class TestMessageContent:
    """Tests for notification message content."""

    @patch('tasks.sold_out_alert.TagNotificationRouter.send_event_notification')
    async def test_includes_event_name_and_artist(
        self, mock_send, service, sample_event_uuid, sample_event_data
    ):
        """Test that message includes event name and artist."""
        from tasks.notification_router import NotificationRoutingResult

        mock_send.return_value = NotificationRoutingResult(
            event_id=sample_event_uuid,
            notification_type='sold_out',
            total_webhooks=1,
            successful_deliveries=1,
        )

        await service.check_and_alert_sold_out(
            event_uuid=sample_event_uuid,
            previous_is_sold_out=False,
            current_is_sold_out=True,
            event_data=sample_event_data,
        )

        call_kwargs = mock_send.call_args.kwargs
        # Artist - Event Name format
        assert 'Taylor Swift' in call_kwargs['event_name']
        assert 'Eras Tour' in call_kwargs['event_name']

    @patch('tasks.sold_out_alert.TagNotificationRouter.send_event_notification')
    async def test_includes_venue(self, mock_send, service, sample_event_uuid, sample_event_data):
        """Test that message includes venue."""
        from tasks.notification_router import NotificationRoutingResult

        mock_send.return_value = NotificationRoutingResult(
            event_id=sample_event_uuid,
            notification_type='sold_out',
            total_webhooks=1,
            successful_deliveries=1,
        )

        await service.check_and_alert_sold_out(
            event_uuid=sample_event_uuid,
            previous_is_sold_out=False,
            current_is_sold_out=True,
            event_data=sample_event_data,
        )

        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs['venue'] == 'United Center'

    @patch('tasks.sold_out_alert.TagNotificationRouter.send_event_notification')
    async def test_includes_last_known_prices(
        self, mock_send, service, sample_event_uuid, sample_event_data
    ):
        """Test that message includes last known prices."""
        from tasks.notification_router import NotificationRoutingResult

        mock_send.return_value = NotificationRoutingResult(
            event_id=sample_event_uuid,
            notification_type='sold_out',
            total_webhooks=1,
            successful_deliveries=1,
        )

        await service.check_and_alert_sold_out(
            event_uuid=sample_event_uuid,
            previous_is_sold_out=False,
            current_is_sold_out=True,
            event_data=sample_event_data,
        )

        call_kwargs = mock_send.call_args.kwargs
        assert 'prices' in call_kwargs
        prices = call_kwargs['prices']
        assert len(prices) == 2  # Low and high price
        assert prices[0]['price'] == 150.00
        assert prices[1]['price'] == 450.00

        # Also check additional_info has last known price
        additional_info = call_kwargs['additional_info']
        assert 'Last Known Price' in additional_info
        assert '$150.00' in additional_info['Last Known Price']
        assert '$450.00' in additional_info['Last Known Price']

    @patch('tasks.sold_out_alert.TagNotificationRouter.send_event_notification')
    async def test_includes_url(self, mock_send, service, sample_event_uuid, sample_event_data):
        """Test that message includes ticket URL."""
        from tasks.notification_router import NotificationRoutingResult

        mock_send.return_value = NotificationRoutingResult(
            event_id=sample_event_uuid,
            notification_type='sold_out',
            total_webhooks=1,
            successful_deliveries=1,
        )

        await service.check_and_alert_sold_out(
            event_uuid=sample_event_uuid,
            previous_is_sold_out=False,
            current_is_sold_out=True,
            event_data=sample_event_data,
        )

        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs['url'] == 'https://tickets.example.com/taylor-swift-eras-tour'

    @patch('tasks.sold_out_alert.TagNotificationRouter.send_event_notification')
    async def test_includes_date_and_time(
        self, mock_send, service, sample_event_uuid, sample_event_data
    ):
        """Test that message includes date and time in additional info."""
        from tasks.notification_router import NotificationRoutingResult

        mock_send.return_value = NotificationRoutingResult(
            event_id=sample_event_uuid,
            notification_type='sold_out',
            total_webhooks=1,
            successful_deliveries=1,
        )

        await service.check_and_alert_sold_out(
            event_uuid=sample_event_uuid,
            previous_is_sold_out=False,
            current_is_sold_out=True,
            event_data=sample_event_data,
        )

        call_kwargs = mock_send.call_args.kwargs
        additional_info = call_kwargs['additional_info']
        assert 'Date' in additional_info
        assert '2025-06-15' in additional_info['Date']
        assert '19:30:00' in additional_info['Date']

    @patch('tasks.sold_out_alert.TagNotificationRouter.send_event_notification')
    async def test_includes_sold_out_status(
        self, mock_send, service, sample_event_uuid, sample_event_data
    ):
        """Test that message includes sold out status indicator."""
        from tasks.notification_router import NotificationRoutingResult

        mock_send.return_value = NotificationRoutingResult(
            event_id=sample_event_uuid,
            notification_type='sold_out',
            total_webhooks=1,
            successful_deliveries=1,
        )

        await service.check_and_alert_sold_out(
            event_uuid=sample_event_uuid,
            previous_is_sold_out=False,
            current_is_sold_out=True,
            event_data=sample_event_data,
        )

        call_kwargs = mock_send.call_args.kwargs
        additional_info = call_kwargs['additional_info']
        assert 'Status' in additional_info
        assert 'SOLD OUT' in additional_info['Status']

    @patch('tasks.sold_out_alert.TagNotificationRouter.send_event_notification')
    async def test_availability_is_out_of_stock(
        self, mock_send, service, sample_event_uuid, sample_event_data
    ):
        """Test that availability is set to 'out_of_stock' for sell outs."""
        from tasks.notification_router import NotificationRoutingResult

        mock_send.return_value = NotificationRoutingResult(
            event_id=sample_event_uuid,
            notification_type='sold_out',
            total_webhooks=1,
            successful_deliveries=1,
        )

        await service.check_and_alert_sold_out(
            event_uuid=sample_event_uuid,
            previous_is_sold_out=False,
            current_is_sold_out=True,
            event_data=sample_event_data,
        )

        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs['availability'] == 'out_of_stock'


# =============================================================================
# Event Data Fetching Tests
# =============================================================================


class TestEventDataFetching:
    """Tests for event data fetching from database."""

    @patch('tasks.sold_out_alert.TagNotificationRouter.send_event_notification')
    @patch('tasks.sold_out_alert.Event.get_by_id')
    async def test_fetches_event_data_when_not_provided(
        self, mock_get_event, mock_send, service, mock_store, sample_event_uuid
    ):
        """Test that event data is fetched from DB when not provided."""
        from tasks.notification_router import NotificationRoutingResult

        # Setup mock event
        mock_event = MagicMock()
        mock_event.event_name = 'Concert'
        mock_event.artist = 'Artist'
        mock_event.venue = 'Venue'
        mock_event.event_date = None
        mock_event.event_time = None
        mock_event.current_price_low = Decimal('100.00')
        mock_event.current_price_high = Decimal('200.00')
        mock_event.url = 'https://example.com'
        mock_event.is_sold_out = True
        mock_get_event.return_value = mock_event

        mock_send.return_value = NotificationRoutingResult(
            event_id=sample_event_uuid,
            notification_type='sold_out',
            total_webhooks=1,
            successful_deliveries=1,
        )

        result = await service.check_and_alert_sold_out(
            event_uuid=sample_event_uuid,
            previous_is_sold_out=False,
            current_is_sold_out=True,
            event_data=None,  # Not provided
        )

        assert result.is_sold_out is True
        mock_get_event.assert_called_once()

    @patch('tasks.sold_out_alert.Event.get_by_id')
    async def test_returns_error_when_event_not_found(
        self, mock_get_event, service, mock_store, sample_event_uuid
    ):
        """Test error handling when event not found in database."""
        mock_get_event.return_value = None

        result = await service.check_and_alert_sold_out(
            event_uuid=sample_event_uuid,
            previous_is_sold_out=False,
            current_is_sold_out=True,
            event_data=None,
        )

        assert result.is_sold_out is True
        assert result.alert_sent is False
        assert 'not found' in result.error_message.lower()


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling scenarios."""

    @patch('tasks.sold_out_alert.TagNotificationRouter.send_event_notification')
    async def test_handles_notification_failure(
        self, mock_send, service, sample_event_uuid, sample_event_data
    ):
        """Test handling when notification sending fails."""
        from tasks.notification_router import NotificationRoutingResult

        mock_send.return_value = NotificationRoutingResult(
            event_id=sample_event_uuid,
            notification_type='sold_out',
            total_webhooks=1,
            successful_deliveries=0,
            failed_deliveries=1,
        )

        result = await service.check_and_alert_sold_out(
            event_uuid=sample_event_uuid,
            previous_is_sold_out=False,
            current_is_sold_out=True,
            event_data=sample_event_data,
        )

        assert result.is_sold_out is True
        assert result.alert_sent is False  # No successful deliveries

    @patch('tasks.sold_out_alert.TagNotificationRouter.send_event_notification')
    async def test_handles_exception_during_send(
        self, mock_send, service, sample_event_uuid, sample_event_data
    ):
        """Test handling when exception occurs during send."""
        mock_send.side_effect = Exception('Network error')

        result = await service.check_and_alert_sold_out(
            event_uuid=sample_event_uuid,
            previous_is_sold_out=False,
            current_is_sold_out=True,
            event_data=sample_event_data,
        )

        assert result.is_sold_out is True
        assert result.alert_sent is False
        assert 'Network error' in result.error_message


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and special scenarios."""

    @patch('tasks.sold_out_alert.TagNotificationRouter.send_event_notification')
    async def test_handles_minimal_event_data(self, mock_send, service, sample_event_uuid):
        """Test with minimal event data (only required fields)."""
        from tasks.notification_router import NotificationRoutingResult

        mock_send.return_value = NotificationRoutingResult(
            event_id=sample_event_uuid,
            notification_type='sold_out',
            total_webhooks=1,
            successful_deliveries=1,
        )

        minimal_data = {
            'url': 'https://example.com',
        }

        result = await service.check_and_alert_sold_out(
            event_uuid=sample_event_uuid,
            previous_is_sold_out=False,
            current_is_sold_out=True,
            event_data=minimal_data,
        )

        assert result.is_sold_out is True
        assert result.alert_sent is True

    @patch('tasks.sold_out_alert.TagNotificationRouter.send_event_notification')
    async def test_handles_single_price(self, mock_send, service, sample_event_uuid):
        """Test with single price (low == high)."""
        from tasks.notification_router import NotificationRoutingResult

        mock_send.return_value = NotificationRoutingResult(
            event_id=sample_event_uuid,
            notification_type='sold_out',
            total_webhooks=1,
            successful_deliveries=1,
        )

        data = {
            'event_name': 'Test Event',
            'current_price_low': 100.00,
            'current_price_high': 100.00,  # Same as low
            'url': 'https://example.com',
        }

        await service.check_and_alert_sold_out(
            event_uuid=sample_event_uuid,
            previous_is_sold_out=False,
            current_is_sold_out=True,
            event_data=data,
        )

        call_kwargs = mock_send.call_args.kwargs
        # Should have only one price entry when low == high
        assert len(call_kwargs['prices']) == 1
        # Last known price should also be single value
        assert '$100.00' in call_kwargs['additional_info']['Last Known Price']

    @patch('tasks.sold_out_alert.TagNotificationRouter.send_event_notification')
    async def test_handles_no_prices(self, mock_send, service, sample_event_uuid):
        """Test with no price information."""
        from tasks.notification_router import NotificationRoutingResult

        mock_send.return_value = NotificationRoutingResult(
            event_id=sample_event_uuid,
            notification_type='sold_out',
            total_webhooks=1,
            successful_deliveries=1,
        )

        data = {
            'event_name': 'Test Event',
            'url': 'https://example.com',
            # No prices
        }

        result = await service.check_and_alert_sold_out(
            event_uuid=sample_event_uuid,
            previous_is_sold_out=False,
            current_is_sold_out=True,
            event_data=data,
        )

        assert result.alert_sent is True
        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs['prices'] == []
        # No Last Known Price field since there are no prices
        assert 'Last Known Price' not in call_kwargs['additional_info']


# =============================================================================
# Convenience Function Tests
# =============================================================================


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    @patch('tasks.sold_out_alert.SoldOutAlertService.check_and_alert_sold_out')
    async def test_send_sold_out_alert(
        self, mock_check, mock_store, sample_event_uuid, sample_event_data
    ):
        """Test send_sold_out_alert convenience function."""
        mock_check.return_value = SoldOutAlertResult(
            event_id=sample_event_uuid,
            is_sold_out=True,
            alert_sent=True,
        )

        result = await send_sold_out_alert(
            store=mock_store,
            event_uuid=sample_event_uuid,
            event_data=sample_event_data,
            default_webhook_url='https://hooks.slack.com/default',
        )

        assert result.is_sold_out is True
        mock_check.assert_called_once()

    @patch('tasks.sold_out_alert.SoldOutAlertService.process_availability_change')
    async def test_check_availability_change_for_sold_out(
        self, mock_process, mock_store, sample_event_uuid, sample_event_data
    ):
        """Test check_availability_change_for_sold_out convenience function."""
        mock_process.return_value = SoldOutAlertResult(
            event_id=sample_event_uuid,
            is_sold_out=True,
            alert_sent=True,
        )

        result = await check_availability_change_for_sold_out(
            store=mock_store,
            event_uuid=sample_event_uuid,
            old_is_sold_out=False,
            new_is_sold_out=True,
            event_data=sample_event_data,
            default_webhook_url='https://hooks.slack.com/default',
        )

        assert result.is_sold_out is True
        mock_process.assert_called_once_with(
            event_uuid=sample_event_uuid,
            old_is_sold_out=False,
            new_is_sold_out=True,
            event_data=sample_event_data,
        )


# =============================================================================
# Process Availability Change Tests
# =============================================================================


class TestProcessAvailabilityChange:
    """Tests for process_availability_change method."""

    @patch('tasks.sold_out_alert.TagNotificationRouter.send_event_notification')
    async def test_process_availability_change_sell_out(
        self, mock_send, service, sample_event_uuid, sample_event_data
    ):
        """Test process_availability_change for a sell out."""
        from tasks.notification_router import NotificationRoutingResult

        mock_send.return_value = NotificationRoutingResult(
            event_id=sample_event_uuid,
            notification_type='sold_out',
            total_webhooks=1,
            successful_deliveries=1,
        )

        result = await service.process_availability_change(
            event_uuid=sample_event_uuid,
            old_is_sold_out=False,
            new_is_sold_out=True,
            event_data=sample_event_data,
        )

        assert result.is_sold_out is True
        assert result.alert_sent is True

    async def test_process_availability_change_not_sell_out(
        self, service, sample_event_uuid, sample_event_data
    ):
        """Test process_availability_change for a non-sell-out."""
        result = await service.process_availability_change(
            event_uuid=sample_event_uuid,
            old_is_sold_out=True,
            new_is_sold_out=False,  # Restock, not sell out
            event_data=sample_event_data,
        )

        assert result.is_sold_out is False
        assert result.alert_sent is False


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Integration-style tests for the full sold out alert flow."""

    @patch('tasks.sold_out_alert.TagNotificationRouter.send_event_notification')
    async def test_full_sold_out_alert_flow(
        self, mock_send, service, sample_event_uuid, sample_event_data
    ):
        """Test complete flow from detection to notification."""
        from tasks.notification_router import NotificationRoutingResult, WebhookDeliveryResult

        # Setup mock notification result
        notification_result = NotificationRoutingResult(
            event_id=sample_event_uuid,
            notification_type='sold_out',
            total_webhooks=2,
            successful_deliveries=2,
            failed_deliveries=0,
        )
        notification_result.deliveries = [
            WebhookDeliveryResult(
                webhook_url='https://hooks.slack.com/hook1',
                tag_id='tag1',
                tag_name='concerts',
                success=True,
                response_status=200,
            ),
            WebhookDeliveryResult(
                webhook_url='https://hooks.slack.com/hook2',
                tag_id='tag2',
                tag_name='high-value',
                success=True,
                response_status=200,
            ),
        ]
        mock_send.return_value = notification_result

        # Execute sold out alert
        result = await service.check_and_alert_sold_out(
            event_uuid=sample_event_uuid,
            previous_is_sold_out=False,
            current_is_sold_out=True,
            event_data=sample_event_data,
        )

        # Verify results
        assert result.is_sold_out is True
        assert result.alert_sent is True
        assert result.success is True
        assert result.notification_result.total_webhooks == 2
        assert result.notification_result.all_successful is True

        # Verify message content
        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs['notification_type'] == 'sold_out'
        assert 'Taylor Swift' in call_kwargs['event_name']
        assert call_kwargs['venue'] == 'United Center'
        assert call_kwargs['availability'] == 'out_of_stock'
        assert 'SOLD OUT' in call_kwargs['additional_info']['Status']
        assert 'Last Known Price' in call_kwargs['additional_info']

    @patch('tasks.sold_out_alert.TagNotificationRouter.send_event_notification')
    async def test_partial_delivery_success(
        self, mock_send, service, sample_event_uuid, sample_event_data
    ):
        """Test when some webhooks succeed and some fail."""
        from tasks.notification_router import NotificationRoutingResult, WebhookDeliveryResult

        notification_result = NotificationRoutingResult(
            event_id=sample_event_uuid,
            notification_type='sold_out',
            total_webhooks=2,
            successful_deliveries=1,
            failed_deliveries=1,
        )
        notification_result.deliveries = [
            WebhookDeliveryResult(
                webhook_url='https://hooks.slack.com/hook1',
                tag_id='tag1',
                tag_name='working',
                success=True,
                response_status=200,
            ),
            WebhookDeliveryResult(
                webhook_url='https://hooks.slack.com/hook2',
                tag_id='tag2',
                tag_name='broken',
                success=False,
                response_status=500,
                error_message='Server error',
            ),
        ]
        mock_send.return_value = notification_result

        result = await service.check_and_alert_sold_out(
            event_uuid=sample_event_uuid,
            previous_is_sold_out=False,
            current_is_sold_out=True,
            event_data=sample_event_data,
        )

        # Alert should be considered sent if any webhook succeeded
        assert result.is_sold_out is True
        assert result.alert_sent is True  # At least one succeeded
        assert result.notification_result.any_successful is True
        assert result.notification_result.all_successful is False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
