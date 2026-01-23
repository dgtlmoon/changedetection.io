"""
Unit tests for the Tag-Based Notification Router.

Tests cover:
- Tag webhook lookup and routing
- Notification muting
- Default webhook fallback
- Notification logging
- Webhook failure handling
- Multiple webhook delivery

Run with: pytest tasks/test_notification_router.py -v
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tasks.notification_router import (
    NotificationRoutingResult,
    TagNotificationRouter,
    WebhookDeliveryResult,
    send_notification_for_event,
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
def router(mock_store):
    """Create a TagNotificationRouter with mock store."""
    return TagNotificationRouter(
        store=mock_store,
        default_webhook_url='https://hooks.slack.com/default',
        use_blocks=True,
    )


@pytest.fixture
def sample_event_uuid():
    """Return a sample event UUID."""
    return str(uuid.uuid4())


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
            'tag_name': 'vip-alerts',
            'webhook_url': 'https://hooks.slack.com/services/T123/B789/def456',
        },
    ]


# =============================================================================
# WebhookDeliveryResult Tests
# =============================================================================


class TestWebhookDeliveryResult:
    """Tests for WebhookDeliveryResult dataclass."""

    def test_successful_delivery_result(self):
        """Test creating a successful delivery result."""
        result = WebhookDeliveryResult(
            webhook_url='https://hooks.slack.com/test',
            tag_id='123',
            tag_name='test-tag',
            success=True,
            response_status=200,
        )
        assert result.success is True
        assert result.response_status == 200
        assert result.error_message is None

    def test_failed_delivery_result(self):
        """Test creating a failed delivery result."""
        result = WebhookDeliveryResult(
            webhook_url='https://hooks.slack.com/test',
            tag_id='123',
            tag_name='test-tag',
            success=False,
            response_status=500,
            error_message='Internal Server Error',
        )
        assert result.success is False
        assert result.error_message == 'Internal Server Error'


# =============================================================================
# NotificationRoutingResult Tests
# =============================================================================


class TestNotificationRoutingResult:
    """Tests for NotificationRoutingResult dataclass."""

    def test_all_successful(self):
        """Test all_successful property."""
        result = NotificationRoutingResult(
            event_id='123',
            notification_type='restock',
            total_webhooks=2,
            successful_deliveries=2,
            failed_deliveries=0,
        )
        assert result.all_successful is True

    def test_not_all_successful(self):
        """Test all_successful when some failed."""
        result = NotificationRoutingResult(
            event_id='123',
            notification_type='restock',
            total_webhooks=2,
            successful_deliveries=1,
            failed_deliveries=1,
        )
        assert result.all_successful is False

    def test_any_successful(self):
        """Test any_successful property."""
        result = NotificationRoutingResult(
            event_id='123',
            notification_type='restock',
            total_webhooks=2,
            successful_deliveries=1,
            failed_deliveries=1,
        )
        assert result.any_successful is True

    def test_none_successful(self):
        """Test any_successful when all failed."""
        result = NotificationRoutingResult(
            event_id='123',
            notification_type='restock',
            total_webhooks=2,
            successful_deliveries=0,
            failed_deliveries=2,
        )
        assert result.any_successful is False

    def test_to_dict(self):
        """Test to_dict method."""
        result = NotificationRoutingResult(
            event_id='123',
            notification_type='restock',
            total_webhooks=1,
            successful_deliveries=1,
            used_default_fallback=False,
        )
        result.deliveries.append(
            WebhookDeliveryResult(
                webhook_url='https://hooks.slack.com/test',
                tag_id='456',
                tag_name='concerts',
                success=True,
            )
        )

        d = result.to_dict()
        assert d['event_id'] == '123'
        assert d['notification_type'] == 'restock'
        assert d['total_webhooks'] == 1
        assert len(d['deliveries']) == 1


# =============================================================================
# TagNotificationRouter Basic Tests
# =============================================================================


class TestTagNotificationRouterInit:
    """Tests for router initialization."""

    def test_router_initialization(self, mock_store):
        """Test router initializes with correct attributes."""
        router = TagNotificationRouter(
            store=mock_store,
            default_webhook_url='https://hooks.slack.com/default',
            use_blocks=True,
        )
        assert router.store is mock_store
        assert router.default_webhook_url == 'https://hooks.slack.com/default'
        assert router.use_blocks is True

    def test_router_without_default_webhook(self, mock_store):
        """Test router can be created without default webhook."""
        router = TagNotificationRouter(
            store=mock_store,
            default_webhook_url=None,
        )
        assert router.default_webhook_url is None


# =============================================================================
# Notification Routing Tests
# =============================================================================


class TestNotificationRouting:
    """Tests for the notification routing logic."""

    @patch('tasks.notification_router.requests.post')
    async def test_routes_to_tag_webhooks(
        self, mock_post, router, mock_store, sample_event_uuid, sample_webhooks
    ):
        """Test that notifications are routed to tag webhooks."""
        # Setup mocks
        mock_post.return_value = MagicMock(status_code=200, text='ok')
        mock_store.get_webhooks_for_event = AsyncMock(return_value=sample_webhooks)
        mock_store.get_all_tags_for_watch = AsyncMock(
            return_value={
                sample_webhooks[0]['tag_id']: {'notification_muted': False},
                sample_webhooks[1]['tag_id']: {'notification_muted': False},
            }
        )

        result = await router.send_event_notification(
            event_uuid=sample_event_uuid,
            notification_type='restock',
            event_name='Test Concert',
        )

        assert result.total_webhooks == 2
        assert result.successful_deliveries == 2
        assert result.failed_deliveries == 0
        assert result.used_default_fallback is False
        assert mock_post.call_count == 2

    @patch('tasks.notification_router.requests.post')
    async def test_uses_default_webhook_when_no_tags(
        self, mock_post, router, mock_store, sample_event_uuid
    ):
        """Test fallback to default webhook when no tag webhooks exist."""
        mock_post.return_value = MagicMock(status_code=200, text='ok')
        mock_store.get_webhooks_for_event = AsyncMock(return_value=[])
        mock_store.get_all_tags_for_watch = AsyncMock(return_value={})

        result = await router.send_event_notification(
            event_uuid=sample_event_uuid,
            notification_type='price_change',
            event_name='Test Event',
        )

        assert result.total_webhooks == 1
        assert result.successful_deliveries == 1
        assert result.used_default_fallback is True
        mock_post.assert_called_once()

        # Verify default webhook URL was used
        call_args = mock_post.call_args
        assert call_args[0][0] == 'https://hooks.slack.com/default'

    async def test_no_notification_when_no_webhooks_and_no_default(
        self, mock_store, sample_event_uuid
    ):
        """Test no notification sent when no webhooks available and no default."""
        router = TagNotificationRouter(
            store=mock_store,
            default_webhook_url=None,  # No default
        )
        mock_store.get_webhooks_for_event = AsyncMock(return_value=[])
        mock_store.get_all_tags_for_watch = AsyncMock(return_value={})

        result = await router.send_event_notification(
            event_uuid=sample_event_uuid,
            notification_type='restock',
        )

        assert result.total_webhooks == 0
        assert result.successful_deliveries == 0
        assert result.used_default_fallback is False

    @patch('tasks.notification_router.requests.post')
    async def test_skips_muted_tags(self, mock_post, router, mock_store, sample_event_uuid):
        """Test that muted tags are tracked in skipped count."""
        # get_webhooks_for_event already excludes muted tags
        # We just verify the count
        active_webhook = {
            'tag_id': str(uuid.uuid4()),
            'tag_name': 'active',
            'webhook_url': 'https://hooks.slack.com/active',
        }
        muted_tag_id = str(uuid.uuid4())

        mock_post.return_value = MagicMock(status_code=200, text='ok')
        mock_store.get_webhooks_for_event = AsyncMock(return_value=[active_webhook])
        mock_store.get_all_tags_for_watch = AsyncMock(
            return_value={
                active_webhook['tag_id']: {'notification_muted': False},
                muted_tag_id: {'notification_muted': True},
            }
        )

        result = await router.send_event_notification(
            event_uuid=sample_event_uuid,
            notification_type='restock',
        )

        assert result.total_webhooks == 1
        assert result.skipped_muted == 1


# =============================================================================
# Webhook Failure Handling Tests
# =============================================================================


class TestWebhookFailureHandling:
    """Tests for graceful handling of webhook failures."""

    @patch('tasks.notification_router.requests.post')
    async def test_handles_http_error(
        self, mock_post, router, mock_store, sample_event_uuid, sample_webhooks
    ):
        """Test handling of HTTP error responses."""
        mock_post.return_value = MagicMock(status_code=500, text='Internal Server Error')
        mock_store.get_webhooks_for_event = AsyncMock(return_value=[sample_webhooks[0]])
        mock_store.get_all_tags_for_watch = AsyncMock(
            return_value={
                sample_webhooks[0]['tag_id']: {'notification_muted': False},
            }
        )

        result = await router.send_event_notification(
            event_uuid=sample_event_uuid,
            notification_type='restock',
        )

        assert result.successful_deliveries == 0
        assert result.failed_deliveries == 1
        assert result.deliveries[0].success is False
        assert '500' in result.deliveries[0].error_message

    @patch('tasks.notification_router.requests.post')
    async def test_handles_timeout(
        self, mock_post, router, mock_store, sample_event_uuid, sample_webhooks
    ):
        """Test handling of request timeouts."""
        import requests

        mock_post.side_effect = requests.exceptions.Timeout()
        mock_store.get_webhooks_for_event = AsyncMock(return_value=[sample_webhooks[0]])
        mock_store.get_all_tags_for_watch = AsyncMock(
            return_value={
                sample_webhooks[0]['tag_id']: {'notification_muted': False},
            }
        )

        result = await router.send_event_notification(
            event_uuid=sample_event_uuid,
            notification_type='restock',
        )

        assert result.failed_deliveries == 1
        assert 'timeout' in result.deliveries[0].error_message.lower()

    @patch('tasks.notification_router.requests.post')
    async def test_handles_connection_error(
        self, mock_post, router, mock_store, sample_event_uuid, sample_webhooks
    ):
        """Test handling of connection errors."""
        import requests

        mock_post.side_effect = requests.exceptions.ConnectionError('Connection refused')
        mock_store.get_webhooks_for_event = AsyncMock(return_value=[sample_webhooks[0]])
        mock_store.get_all_tags_for_watch = AsyncMock(
            return_value={
                sample_webhooks[0]['tag_id']: {'notification_muted': False},
            }
        )

        result = await router.send_event_notification(
            event_uuid=sample_event_uuid,
            notification_type='restock',
        )

        assert result.failed_deliveries == 1
        assert result.deliveries[0].error_message is not None

    @patch('tasks.notification_router.requests.post')
    async def test_continues_after_failure(
        self, mock_post, router, mock_store, sample_event_uuid, sample_webhooks
    ):
        """Test that router continues to next webhook after failure."""
        # First call fails, second succeeds
        mock_post.side_effect = [
            MagicMock(status_code=500, text='Error'),
            MagicMock(status_code=200, text='ok'),
        ]
        mock_store.get_webhooks_for_event = AsyncMock(return_value=sample_webhooks)
        mock_store.get_all_tags_for_watch = AsyncMock(
            return_value={
                sample_webhooks[0]['tag_id']: {'notification_muted': False},
                sample_webhooks[1]['tag_id']: {'notification_muted': False},
            }
        )

        result = await router.send_event_notification(
            event_uuid=sample_event_uuid,
            notification_type='restock',
        )

        assert result.total_webhooks == 2
        assert result.successful_deliveries == 1
        assert result.failed_deliveries == 1
        assert mock_post.call_count == 2


# =============================================================================
# Notification Logging Tests
# =============================================================================


class TestNotificationLogging:
    """Tests for notification logging functionality."""

    @patch('tasks.notification_router.requests.post')
    @patch('tasks.notification_router.NotificationLog.log_notification')
    async def test_logs_successful_notification(
        self, mock_log, mock_post, router, mock_store, sample_event_uuid, sample_webhooks
    ):
        """Test that successful notifications are logged."""
        mock_post.return_value = MagicMock(status_code=200, text='ok')
        mock_log.return_value = MagicMock()
        mock_store.get_webhooks_for_event = AsyncMock(return_value=[sample_webhooks[0]])
        mock_store.get_all_tags_for_watch = AsyncMock(
            return_value={
                sample_webhooks[0]['tag_id']: {'notification_muted': False},
            }
        )

        await router.send_event_notification(
            event_uuid=sample_event_uuid,
            notification_type='restock',
        )

        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs['success'] is True
        assert call_kwargs['notification_type'] == 'restock'

    @patch('tasks.notification_router.requests.post')
    @patch('tasks.notification_router.NotificationLog.log_notification')
    async def test_logs_failed_notification(
        self, mock_log, mock_post, router, mock_store, sample_event_uuid, sample_webhooks
    ):
        """Test that failed notifications are logged with error details."""
        mock_post.return_value = MagicMock(status_code=500, text='Server Error')
        mock_log.return_value = MagicMock()
        mock_store.get_webhooks_for_event = AsyncMock(return_value=[sample_webhooks[0]])
        mock_store.get_all_tags_for_watch = AsyncMock(
            return_value={
                sample_webhooks[0]['tag_id']: {'notification_muted': False},
            }
        )

        await router.send_event_notification(
            event_uuid=sample_event_uuid,
            notification_type='restock',
        )

        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs['success'] is False
        assert call_kwargs['error_message'] is not None
        assert call_kwargs['response_status'] == 500


# =============================================================================
# Test Notification Tests
# =============================================================================


class TestTestNotification:
    """Tests for the test notification functionality."""

    @patch('tasks.notification_router.requests.post')
    async def test_send_test_notification_success(self, mock_post, router):
        """Test successful test notification."""
        mock_post.return_value = MagicMock(status_code=200, text='ok')

        result = await router.send_test_notification(
            webhook_url='https://hooks.slack.com/test',
            tag_name='test-tag',
        )

        assert result.success is True
        assert result.response_status == 200
        mock_post.assert_called_once()

    @patch('tasks.notification_router.requests.post')
    async def test_send_test_notification_failure(self, mock_post, router):
        """Test failed test notification."""
        mock_post.return_value = MagicMock(status_code=404, text='Not Found')

        result = await router.send_test_notification(
            webhook_url='https://hooks.slack.com/invalid',
        )

        assert result.success is False
        assert result.response_status == 404


# =============================================================================
# Convenience Function Tests
# =============================================================================


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    @patch('tasks.notification_router.requests.post')
    async def test_send_notification_for_event(self, mock_post, mock_store, sample_event_uuid):
        """Test send_notification_for_event convenience function."""
        mock_post.return_value = MagicMock(status_code=200, text='ok')
        mock_store.get_webhooks_for_event = AsyncMock(return_value=[])
        mock_store.get_all_tags_for_watch = AsyncMock(return_value={})

        result = await send_notification_for_event(
            store=mock_store,
            event_uuid=sample_event_uuid,
            notification_type='price_change',
            default_webhook_url='https://hooks.slack.com/default',
            event_name='Test Event',
        )

        assert isinstance(result, NotificationRoutingResult)
        assert result.used_default_fallback is True


# =============================================================================
# Message Content Tests
# =============================================================================


class TestMessageContent:
    """Tests for notification message content."""

    @patch('tasks.notification_router.requests.post')
    async def test_message_includes_event_details(
        self, mock_post, router, mock_store, sample_event_uuid, sample_webhooks
    ):
        """Test that message includes event details."""
        mock_post.return_value = MagicMock(status_code=200, text='ok')
        mock_store.get_webhooks_for_event = AsyncMock(return_value=[sample_webhooks[0]])
        mock_store.get_all_tags_for_watch = AsyncMock(
            return_value={
                sample_webhooks[0]['tag_id']: {'notification_muted': False},
            }
        )

        await router.send_event_notification(
            event_uuid=sample_event_uuid,
            notification_type='restock',
            event_name='Taylor Swift Concert',
            venue='Madison Square Garden',
            prices=[{'price': 150, 'currency': 'USD'}],
            url='https://tickets.example.com',
            availability='in_stock',
        )

        # Check that payload was sent
        call_args = mock_post.call_args
        payload = call_args[1]['json']

        # Should have blocks (since use_blocks=True)
        assert 'blocks' in payload

    @patch('tasks.notification_router.requests.post')
    async def test_message_uses_text_when_blocks_disabled(
        self, mock_store, sample_event_uuid, sample_webhooks
    ):
        """Test that plain text is used when blocks are disabled."""
        with patch('tasks.notification_router.requests.post') as mock_post:
            mock_post.return_value = MagicMock(status_code=200, text='ok')

            router = TagNotificationRouter(
                store=mock_store,
                default_webhook_url='https://hooks.slack.com/default',
                use_blocks=False,
            )
            mock_store.get_webhooks_for_event = AsyncMock(return_value=[sample_webhooks[0]])
            mock_store.get_all_tags_for_watch = AsyncMock(
                return_value={
                    sample_webhooks[0]['tag_id']: {'notification_muted': False},
                }
            )

            await router.send_event_notification(
                event_uuid=sample_event_uuid,
                notification_type='restock',
                event_name='Test Event',
            )

            call_args = mock_post.call_args
            payload = call_args[1]['json']
            assert 'text' in payload
            assert 'blocks' not in payload


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Integration-style tests for the full notification flow."""

    @patch('tasks.notification_router.requests.post')
    async def test_full_notification_flow(
        self, mock_post, mock_store, sample_event_uuid, sample_webhooks
    ):
        """Test complete notification flow from event to delivery."""
        # Setup: 3 webhooks, 1 muted, 1 fails
        muted_tag_id = str(uuid.uuid4())
        active_webhooks = sample_webhooks[:2]

        mock_post.side_effect = [
            MagicMock(status_code=200, text='ok'),  # First succeeds
            MagicMock(status_code=500, text='Error'),  # Second fails
        ]
        mock_store.get_webhooks_for_event = AsyncMock(return_value=active_webhooks)
        mock_store.get_all_tags_for_watch = AsyncMock(
            return_value={
                active_webhooks[0]['tag_id']: {'notification_muted': False},
                active_webhooks[1]['tag_id']: {'notification_muted': False},
                muted_tag_id: {'notification_muted': True},
            }
        )

        router = TagNotificationRouter(
            store=mock_store,
            default_webhook_url='https://hooks.slack.com/default',
        )

        result = await router.send_event_notification(
            event_uuid=sample_event_uuid,
            notification_type='price_change',
            event_name='Hamilton',
            venue='Chicago Theatre',
            prices=[
                {'price': 199.00, 'currency': 'USD', 'label': 'Orchestra'},
                {'price': 99.00, 'currency': 'USD', 'label': 'Balcony'},
            ],
            old_prices=[
                {'price': 249.00, 'currency': 'USD'},
            ],
            url='https://tickets.example.com/hamilton',
            availability='limited',
            additional_info={'Date': 'March 15, 2025'},
        )

        # Verify results
        assert result.total_webhooks == 2
        assert result.successful_deliveries == 1
        assert result.failed_deliveries == 1
        assert result.skipped_muted == 1
        assert result.used_default_fallback is False
        assert result.any_successful is True
        assert result.all_successful is False

        # Verify delivery details
        assert len(result.deliveries) == 2
        assert result.deliveries[0].success is True
        assert result.deliveries[1].success is False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
