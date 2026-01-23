"""
Unit tests for the Price Change Alert Service.

Tests cover:
- Price change detection (current_price_low/current_price_high changes)
- Percentage change calculation
- Direction detection (price up vs price down)
- Threshold filtering (min_percent_threshold)
- Notification delivery with old/new prices
- Emoji direction indicators
- Tag webhook routing
- Notification logging with type='price_change'/'price_drop'/'price_increase'
- Error handling and edge cases

Run with: pytest tasks/test_price_change_alert.py -v
"""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tasks.price_change_alert import (
    DEFAULT_MIN_PERCENT_THRESHOLD,
    PRICE_DOWN_EMOJI,
    PRICE_UP_EMOJI,
    PriceChangeAlertResult,
    PriceChangeAlertService,
    PriceChangeInfo,
    check_price_change_for_alert,
    send_price_change_alert,
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
    """Create a PriceChangeAlertService with mock store."""
    return PriceChangeAlertService(
        store=mock_store,
        default_webhook_url='https://hooks.slack.com/default',
        min_percent_threshold=1.0,  # 1% threshold
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
        'current_price_low': 90.00,
        'current_price_high': 180.00,
        'url': 'https://tickets.example.com/taylor-swift-eras-tour',
        'is_sold_out': False,
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
# PriceChangeInfo Tests
# =============================================================================


class TestPriceChangeInfo:
    """Tests for the PriceChangeInfo dataclass."""

    def test_no_change_detected(self):
        """Test when prices haven't changed."""
        info = PriceChangeInfo(
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=100.00,
            new_price_high=200.00,
        )
        assert info.has_change is False
        assert info.direction == 'mixed'

    def test_low_price_decrease(self):
        """Test detection of low price decrease."""
        info = PriceChangeInfo(
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=90.00,
            new_price_high=200.00,
        )
        assert info.has_change is True
        assert info.direction == 'down'
        abs_change, pct_change = info.low_price_change
        assert abs_change == -10.0
        assert pct_change == -10.0

    def test_low_price_increase(self):
        """Test detection of low price increase."""
        info = PriceChangeInfo(
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=110.00,
            new_price_high=200.00,
        )
        assert info.has_change is True
        assert info.direction == 'up'
        abs_change, pct_change = info.low_price_change
        assert abs_change == 10.0
        assert pct_change == 10.0

    def test_high_price_decrease(self):
        """Test detection of high price decrease."""
        info = PriceChangeInfo(
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=100.00,
            new_price_high=180.00,
        )
        assert info.has_change is True
        # Direction based on low price if available, but low didn't change
        # So high price decrease should reflect in primary_change
        abs_change, pct_change = info.high_price_change
        assert abs_change == -20.0
        assert pct_change == -10.0

    def test_high_price_increase(self):
        """Test detection of high price increase."""
        info = PriceChangeInfo(
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=100.00,
            new_price_high=220.00,
        )
        assert info.has_change is True
        abs_change, pct_change = info.high_price_change
        assert abs_change == 20.0
        assert pct_change == 10.0

    def test_both_prices_decrease(self):
        """Test when both prices decrease."""
        info = PriceChangeInfo(
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=90.00,
            new_price_high=180.00,
        )
        assert info.has_change is True
        assert info.direction == 'down'
        # Primary change is low price
        abs_change, pct_change = info.primary_change
        assert abs_change == -10.0
        assert pct_change == -10.0

    def test_both_prices_increase(self):
        """Test when both prices increase."""
        info = PriceChangeInfo(
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=110.00,
            new_price_high=220.00,
        )
        assert info.has_change is True
        assert info.direction == 'up'
        abs_change, pct_change = info.primary_change
        assert abs_change == 10.0
        assert pct_change == 10.0

    def test_direction_emoji_down(self):
        """Test emoji for price decrease."""
        info = PriceChangeInfo(
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=90.00,
            new_price_high=180.00,
        )
        assert info.direction_emoji == PRICE_DOWN_EMOJI

    def test_direction_emoji_up(self):
        """Test emoji for price increase."""
        info = PriceChangeInfo(
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=110.00,
            new_price_high=220.00,
        )
        assert info.direction_emoji == PRICE_UP_EMOJI

    def test_notification_type_price_drop(self):
        """Test notification type for price decrease."""
        info = PriceChangeInfo(
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=90.00,
            new_price_high=180.00,
        )
        assert info.notification_type == 'price_drop'

    def test_notification_type_price_increase(self):
        """Test notification type for price increase."""
        info = PriceChangeInfo(
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=110.00,
            new_price_high=220.00,
        )
        assert info.notification_type == 'price_increase'

    def test_threshold_exceeded(self):
        """Test threshold detection for significant changes."""
        info = PriceChangeInfo(
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=90.00,
            new_price_high=180.00,
        )
        assert info.exceeds_threshold(5.0) is True  # 10% > 5%
        assert info.exceeds_threshold(15.0) is False  # 10% < 15%

    def test_threshold_not_exceeded_small_change(self):
        """Test threshold for minor price fluctuations."""
        info = PriceChangeInfo(
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=100.50,
            new_price_high=201.00,
        )
        assert info.exceeds_threshold(1.0) is False  # 0.5% < 1%

    def test_format_change_summary(self):
        """Test human-readable change summary."""
        info = PriceChangeInfo(
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=90.00,
            new_price_high=180.00,
        )
        summary = info.format_change_summary()
        assert 'Low:' in summary
        assert '$100.00' in summary
        assert '$90.00' in summary
        assert '-10.0%' in summary

    def test_format_change_summary_single_price(self):
        """Test summary when only low price changes."""
        info = PriceChangeInfo(
            old_price_low=100.00,
            old_price_high=100.00,  # Same as low
            new_price_low=90.00,
            new_price_high=90.00,  # Same as low
        )
        summary = info.format_change_summary()
        # Should show low price change
        assert '$100.00' in summary
        assert '$90.00' in summary

    def test_decimal_prices(self):
        """Test with Decimal price values."""
        info = PriceChangeInfo(
            old_price_low=Decimal('100.00'),
            old_price_high=Decimal('200.00'),
            new_price_low=Decimal('90.00'),
            new_price_high=Decimal('180.00'),
        )
        assert info.has_change is True
        assert info.direction == 'down'
        abs_change, pct_change = info.low_price_change
        assert abs_change == -10.0
        assert pct_change == -10.0

    def test_none_old_price(self):
        """Test when old price is None."""
        info = PriceChangeInfo(
            old_price_low=None,
            old_price_high=200.00,
            new_price_low=90.00,
            new_price_high=180.00,
        )
        assert info.has_change is True
        # Low price change calculation returns None
        abs_change, pct_change = info.low_price_change
        assert abs_change is None
        assert pct_change is None

    def test_none_new_price(self):
        """Test when new price is None."""
        info = PriceChangeInfo(
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=None,
            new_price_high=180.00,
        )
        assert info.has_change is True
        abs_change, pct_change = info.low_price_change
        assert abs_change is None
        assert pct_change is None

    def test_zero_old_price(self):
        """Test edge case with zero old price."""
        info = PriceChangeInfo(
            old_price_low=0.00,
            old_price_high=200.00,
            new_price_low=50.00,
            new_price_high=200.00,
        )
        # Division by zero should be handled
        abs_change, pct_change = info.low_price_change
        assert abs_change == 50.0
        assert pct_change is None  # Can't calculate percentage from 0


# =============================================================================
# PriceChangeAlertResult Tests
# =============================================================================


class TestPriceChangeAlertResult:
    """Tests for the PriceChangeAlertResult dataclass."""

    def test_success_property_true(self):
        """Test success property when alert was sent."""
        result = PriceChangeAlertResult(
            event_id='test-uuid',
            is_price_change=True,
            exceeds_threshold=True,
            alert_sent=True,
        )
        assert result.success is True

    def test_success_property_false_no_change(self):
        """Test success property when no price change."""
        result = PriceChangeAlertResult(
            event_id='test-uuid',
            is_price_change=False,
            exceeds_threshold=False,
            alert_sent=False,
        )
        assert result.success is False

    def test_success_property_false_below_threshold(self):
        """Test success property when change below threshold."""
        result = PriceChangeAlertResult(
            event_id='test-uuid',
            is_price_change=True,
            exceeds_threshold=False,
            alert_sent=False,
        )
        assert result.success is False

    def test_success_property_false_alert_failed(self):
        """Test success property when alert sending failed."""
        result = PriceChangeAlertResult(
            event_id='test-uuid',
            is_price_change=True,
            exceeds_threshold=True,
            alert_sent=False,
        )
        assert result.success is False

    def test_to_dict(self):
        """Test conversion to dictionary."""
        price_info = PriceChangeInfo(
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=90.00,
            new_price_high=180.00,
        )
        result = PriceChangeAlertResult(
            event_id='test-uuid',
            is_price_change=True,
            exceeds_threshold=True,
            alert_sent=True,
            price_info=price_info,
        )
        result_dict = result.to_dict()
        assert result_dict['event_id'] == 'test-uuid'
        assert result_dict['is_price_change'] is True
        assert result_dict['exceeds_threshold'] is True
        assert result_dict['alert_sent'] is True
        assert result_dict['price_info']['direction'] == 'down'


# =============================================================================
# PriceChangeAlertService Tests
# =============================================================================


class TestPriceChangeAlertService:
    """Tests for the PriceChangeAlertService class."""

    def test_init_default_threshold(self, mock_store):
        """Test initialization with default threshold."""
        service = PriceChangeAlertService(store=mock_store)
        assert service.min_percent_threshold == DEFAULT_MIN_PERCENT_THRESHOLD

    def test_init_custom_threshold(self, mock_store):
        """Test initialization with custom threshold."""
        service = PriceChangeAlertService(store=mock_store, min_percent_threshold=5.0)
        assert service.min_percent_threshold == 5.0

    def test_is_significant_change_true(self, service):
        """Test significant change detection returns True for large changes."""
        is_sig, info = service.is_significant_change(
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=90.00,
            new_price_high=180.00,
        )
        assert is_sig is True
        assert info.has_change is True

    def test_is_significant_change_false_no_change(self, service):
        """Test significant change detection returns False when no change."""
        is_sig, info = service.is_significant_change(
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=100.00,
            new_price_high=200.00,
        )
        assert is_sig is False
        assert info.has_change is False

    def test_is_significant_change_false_below_threshold(self, service):
        """Test significant change detection returns False for small changes."""
        is_sig, info = service.is_significant_change(
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=100.50,  # 0.5% change
            new_price_high=201.00,  # 0.5% change
        )
        assert is_sig is False
        assert info.has_change is True  # Change exists but not significant

    async def test_check_and_alert_no_change(self, service, sample_event_uuid):
        """Test check_and_alert when no price change."""
        result = await service.check_and_alert_price_change(
            event_uuid=sample_event_uuid,
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=100.00,
            new_price_high=200.00,
        )
        assert result.is_price_change is False
        assert result.exceeds_threshold is False
        assert result.alert_sent is False

    async def test_check_and_alert_below_threshold(self, service, sample_event_uuid):
        """Test check_and_alert when change below threshold."""
        result = await service.check_and_alert_price_change(
            event_uuid=sample_event_uuid,
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=100.50,
            new_price_high=201.00,
        )
        assert result.is_price_change is True
        assert result.exceeds_threshold is False
        assert result.alert_sent is False

    @patch('tasks.price_change_alert.TagNotificationRouter')
    async def test_check_and_alert_sends_notification(
        self, mock_router_class, mock_store, sample_event_uuid, sample_event_data
    ):
        """Test check_and_alert sends notification for significant change."""
        # Set up mock router
        mock_router = AsyncMock()
        mock_notification_result = MagicMock()
        mock_notification_result.any_successful = True
        mock_notification_result.successful_deliveries = 1
        mock_notification_result.total_webhooks = 1
        mock_router.send_event_notification = AsyncMock(return_value=mock_notification_result)
        mock_router_class.return_value = mock_router

        service = PriceChangeAlertService(store=mock_store, min_percent_threshold=1.0)

        result = await service.check_and_alert_price_change(
            event_uuid=sample_event_uuid,
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=90.00,
            new_price_high=180.00,
            event_data=sample_event_data,
        )

        assert result.is_price_change is True
        assert result.exceeds_threshold is True
        assert result.alert_sent is True
        mock_router.send_event_notification.assert_called_once()

    @patch('tasks.price_change_alert.TagNotificationRouter')
    async def test_notification_type_price_drop(
        self, mock_router_class, mock_store, sample_event_uuid, sample_event_data
    ):
        """Test notification type is 'price_drop' for decreases."""
        mock_router = AsyncMock()
        mock_notification_result = MagicMock()
        mock_notification_result.any_successful = True
        mock_notification_result.successful_deliveries = 1
        mock_notification_result.total_webhooks = 1
        mock_router.send_event_notification = AsyncMock(return_value=mock_notification_result)
        mock_router_class.return_value = mock_router

        service = PriceChangeAlertService(store=mock_store, min_percent_threshold=1.0)

        await service.check_and_alert_price_change(
            event_uuid=sample_event_uuid,
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=90.00,
            new_price_high=180.00,
            event_data=sample_event_data,
        )

        # Check notification type in call
        call_kwargs = mock_router.send_event_notification.call_args.kwargs
        assert call_kwargs['notification_type'] == 'price_drop'

    @patch('tasks.price_change_alert.TagNotificationRouter')
    async def test_notification_type_price_increase(
        self, mock_router_class, mock_store, sample_event_uuid, sample_event_data
    ):
        """Test notification type is 'price_increase' for increases."""
        mock_router = AsyncMock()
        mock_notification_result = MagicMock()
        mock_notification_result.any_successful = True
        mock_notification_result.successful_deliveries = 1
        mock_notification_result.total_webhooks = 1
        mock_router.send_event_notification = AsyncMock(return_value=mock_notification_result)
        mock_router_class.return_value = mock_router

        service = PriceChangeAlertService(store=mock_store, min_percent_threshold=1.0)

        # Increase prices
        sample_event_data['current_price_low'] = 110.00
        sample_event_data['current_price_high'] = 220.00

        await service.check_and_alert_price_change(
            event_uuid=sample_event_uuid,
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=110.00,
            new_price_high=220.00,
            event_data=sample_event_data,
        )

        call_kwargs = mock_router.send_event_notification.call_args.kwargs
        assert call_kwargs['notification_type'] == 'price_increase'

    @patch('tasks.price_change_alert.TagNotificationRouter')
    async def test_old_prices_included_in_notification(
        self, mock_router_class, mock_store, sample_event_uuid, sample_event_data
    ):
        """Test that old prices are included in notification for comparison."""
        mock_router = AsyncMock()
        mock_notification_result = MagicMock()
        mock_notification_result.any_successful = True
        mock_notification_result.successful_deliveries = 1
        mock_notification_result.total_webhooks = 1
        mock_router.send_event_notification = AsyncMock(return_value=mock_notification_result)
        mock_router_class.return_value = mock_router

        service = PriceChangeAlertService(store=mock_store, min_percent_threshold=1.0)

        await service.check_and_alert_price_change(
            event_uuid=sample_event_uuid,
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=90.00,
            new_price_high=180.00,
            event_data=sample_event_data,
        )

        call_kwargs = mock_router.send_event_notification.call_args.kwargs
        assert 'old_prices' in call_kwargs
        assert call_kwargs['old_prices'] is not None
        assert len(call_kwargs['old_prices']) > 0

    @patch('tasks.price_change_alert.TagNotificationRouter')
    async def test_percentage_in_additional_info(
        self, mock_router_class, mock_store, sample_event_uuid, sample_event_data
    ):
        """Test that percentage change is included in additional_info."""
        mock_router = AsyncMock()
        mock_notification_result = MagicMock()
        mock_notification_result.any_successful = True
        mock_notification_result.successful_deliveries = 1
        mock_notification_result.total_webhooks = 1
        mock_router.send_event_notification = AsyncMock(return_value=mock_notification_result)
        mock_router_class.return_value = mock_router

        service = PriceChangeAlertService(store=mock_store, min_percent_threshold=1.0)

        await service.check_and_alert_price_change(
            event_uuid=sample_event_uuid,
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=90.00,
            new_price_high=180.00,
            event_data=sample_event_data,
        )

        call_kwargs = mock_router.send_event_notification.call_args.kwargs
        assert 'additional_info' in call_kwargs
        additional_info = call_kwargs['additional_info']
        assert 'Change' in additional_info
        # Should contain percentage
        assert '-10.0%' in additional_info['Change']

    @patch('tasks.price_change_alert.TagNotificationRouter')
    async def test_direction_emoji_in_additional_info(
        self, mock_router_class, mock_store, sample_event_uuid, sample_event_data
    ):
        """Test that direction emoji is included in additional_info."""
        mock_router = AsyncMock()
        mock_notification_result = MagicMock()
        mock_notification_result.any_successful = True
        mock_notification_result.successful_deliveries = 1
        mock_notification_result.total_webhooks = 1
        mock_router.send_event_notification = AsyncMock(return_value=mock_notification_result)
        mock_router_class.return_value = mock_router

        service = PriceChangeAlertService(store=mock_store, min_percent_threshold=1.0)

        await service.check_and_alert_price_change(
            event_uuid=sample_event_uuid,
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=90.00,
            new_price_high=180.00,
            event_data=sample_event_data,
        )

        call_kwargs = mock_router.send_event_notification.call_args.kwargs
        additional_info = call_kwargs['additional_info']
        # Should contain direction emoji
        assert PRICE_DOWN_EMOJI in additional_info['Change']

    @patch('tasks.price_change_alert.Event')
    async def test_fetches_event_data_when_not_provided(
        self, mock_event_class, service, sample_event_uuid
    ):
        """Test that event data is fetched when not provided."""
        # Set up mock event
        mock_event = MagicMock()
        mock_event.event_name = 'Test Event'
        mock_event.artist = 'Test Artist'
        mock_event.venue = 'Test Venue'
        mock_event.event_date = None
        mock_event.event_time = None
        mock_event.current_price_low = Decimal('90.00')
        mock_event.current_price_high = Decimal('180.00')
        mock_event.url = 'https://test.com'
        mock_event.is_sold_out = False
        mock_event_class.get_by_id = AsyncMock(return_value=mock_event)

        # Mock the router
        with patch.object(service, 'router') as mock_router:
            mock_notification_result = MagicMock()
            mock_notification_result.any_successful = True
            mock_notification_result.successful_deliveries = 1
            mock_notification_result.total_webhooks = 1
            mock_router.send_event_notification = AsyncMock(return_value=mock_notification_result)

            result = await service.check_and_alert_price_change(
                event_uuid=sample_event_uuid,
                old_price_low=100.00,
                old_price_high=200.00,
                new_price_low=90.00,
                new_price_high=180.00,
                event_data=None,  # Not provided
            )

            assert result.is_price_change is True
            mock_event_class.get_by_id.assert_called_once()

    @patch('tasks.price_change_alert.Event')
    async def test_handles_event_not_found(self, mock_event_class, service, sample_event_uuid):
        """Test error handling when event not found in database."""
        mock_event_class.get_by_id = AsyncMock(return_value=None)

        result = await service.check_and_alert_price_change(
            event_uuid=sample_event_uuid,
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=90.00,
            new_price_high=180.00,
            event_data=None,
        )

        assert result.is_price_change is True
        assert result.exceeds_threshold is True
        assert result.alert_sent is False
        assert 'not found' in result.error_message

    async def test_process_price_change_alias(self, service, sample_event_uuid):
        """Test that process_price_change is an alias for check_and_alert_price_change."""
        result = await service.process_price_change(
            event_uuid=sample_event_uuid,
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=100.00,
            new_price_high=200.00,
        )
        # Should work the same as check_and_alert_price_change
        assert result.is_price_change is False


# =============================================================================
# Convenience Function Tests
# =============================================================================


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    @patch('tasks.price_change_alert.PriceChangeAlertService')
    async def test_send_price_change_alert(self, mock_service_class, mock_store):
        """Test send_price_change_alert convenience function."""
        mock_service = MagicMock()
        mock_result = PriceChangeAlertResult(
            event_id='test-uuid',
            is_price_change=True,
            exceeds_threshold=True,
            alert_sent=True,
        )
        mock_service.check_and_alert_price_change = AsyncMock(return_value=mock_result)
        mock_service_class.return_value = mock_service

        result = await send_price_change_alert(
            store=mock_store,
            event_uuid='test-uuid',
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=90.00,
            new_price_high=180.00,
        )

        assert result.success is True
        mock_service_class.assert_called_once()
        mock_service.check_and_alert_price_change.assert_called_once()

    @patch('tasks.price_change_alert.PriceChangeAlertService')
    async def test_check_price_change_for_alert(self, mock_service_class, mock_store):
        """Test check_price_change_for_alert convenience function."""
        mock_service = MagicMock()
        mock_result = PriceChangeAlertResult(
            event_id='test-uuid',
            is_price_change=True,
            exceeds_threshold=True,
            alert_sent=True,
        )
        mock_service.process_price_change = AsyncMock(return_value=mock_result)
        mock_service_class.return_value = mock_service

        result = await check_price_change_for_alert(
            store=mock_store,
            event_uuid='test-uuid',
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=90.00,
            new_price_high=180.00,
        )

        assert result.success is True
        mock_service.process_price_change.assert_called_once()

    @patch('tasks.price_change_alert.PriceChangeAlertService')
    async def test_custom_threshold_in_convenience_function(
        self, mock_service_class, mock_store
    ):
        """Test custom threshold is passed to service."""
        mock_service = MagicMock()
        mock_result = PriceChangeAlertResult(
            event_id='test-uuid',
            is_price_change=False,
            exceeds_threshold=False,
            alert_sent=False,
        )
        mock_service.check_and_alert_price_change = AsyncMock(return_value=mock_result)
        mock_service_class.return_value = mock_service

        await send_price_change_alert(
            store=mock_store,
            event_uuid='test-uuid',
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=90.00,
            new_price_high=180.00,
            min_percent_threshold=5.0,
        )

        # Check service was created with custom threshold
        mock_service_class.assert_called_once_with(
            store=mock_store,
            default_webhook_url=None,
            min_percent_threshold=5.0,
        )


# =============================================================================
# Edge Cases and Integration Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_exactly_at_threshold(self):
        """Test price change exactly at threshold boundary."""
        info = PriceChangeInfo(
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=99.00,  # Exactly 1% decrease
            new_price_high=198.00,
        )
        # 1% should pass a 1% threshold
        assert info.exceeds_threshold(1.0) is True

    def test_just_below_threshold(self):
        """Test price change just below threshold."""
        info = PriceChangeInfo(
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=99.50,  # 0.5% decrease
            new_price_high=199.00,
        )
        assert info.exceeds_threshold(1.0) is False

    def test_large_price_increase(self):
        """Test handling of large price increases."""
        info = PriceChangeInfo(
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=200.00,  # 100% increase
            new_price_high=400.00,
        )
        assert info.direction == 'up'
        _, pct = info.primary_change
        assert pct == 100.0

    def test_large_price_decrease(self):
        """Test handling of large price decreases."""
        info = PriceChangeInfo(
            old_price_low=100.00,
            old_price_high=200.00,
            new_price_low=10.00,  # 90% decrease
            new_price_high=20.00,
        )
        assert info.direction == 'down'
        _, pct = info.primary_change
        assert pct == -90.0

    def test_high_precision_decimals(self):
        """Test with high precision decimal prices."""
        info = PriceChangeInfo(
            old_price_low=Decimal('100.99'),
            old_price_high=Decimal('200.49'),
            new_price_low=Decimal('90.89'),
            new_price_high=Decimal('180.44'),
        )
        assert info.has_change is True
        assert info.direction == 'down'

    def test_single_price_only(self):
        """Test when only low price exists (no range)."""
        info = PriceChangeInfo(
            old_price_low=100.00,
            old_price_high=100.00,  # Same as low
            new_price_low=90.00,
            new_price_high=90.00,  # Same as low
        )
        assert info.has_change is True
        assert info.direction == 'down'
        summary = info.format_change_summary()
        # Should not show "High:" since they're the same
        assert summary.count('High:') == 0 or 'High:' not in summary

    async def test_notification_failure_handling(self, service, sample_event_uuid, sample_event_data):
        """Test handling when notification sending fails."""
        with patch.object(service, 'router') as mock_router:
            mock_notification_result = MagicMock()
            mock_notification_result.any_successful = False
            mock_notification_result.successful_deliveries = 0
            mock_notification_result.total_webhooks = 2
            mock_router.send_event_notification = AsyncMock(return_value=mock_notification_result)

            result = await service.check_and_alert_price_change(
                event_uuid=sample_event_uuid,
                old_price_low=100.00,
                old_price_high=200.00,
                new_price_low=90.00,
                new_price_high=180.00,
                event_data=sample_event_data,
            )

            assert result.is_price_change is True
            assert result.exceeds_threshold is True
            assert result.alert_sent is False  # Failed to send

    async def test_exception_during_notification(self, service, sample_event_uuid, sample_event_data):
        """Test handling of exceptions during notification."""
        with patch.object(service, 'router') as mock_router:
            mock_router.send_event_notification = AsyncMock(
                side_effect=Exception("Network error")
            )

            result = await service.check_and_alert_price_change(
                event_uuid=sample_event_uuid,
                old_price_low=100.00,
                old_price_high=200.00,
                new_price_low=90.00,
                new_price_high=180.00,
                event_data=sample_event_data,
            )

            assert result.is_price_change is True
            assert result.exceeds_threshold is True
            assert result.alert_sent is False
            assert result.error_message is not None
            assert 'Network error' in result.error_message
