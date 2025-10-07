"""
Tests for browser notification functionality
Tests VAPID key handling, subscription management, and notification sending
"""

import json
import sys
import tempfile
import os
import unittest
from unittest.mock import patch, Mock, MagicMock
from py_vapid import Vapid

from changedetectionio.notification.apprise_plugin.browser_notification_helpers import (
    convert_pem_private_key_for_pywebpush,
    convert_pem_public_key_for_browser,
    send_push_notifications,
    create_notification_payload,
    get_vapid_config_from_datastore,
    get_browser_subscriptions,
    save_browser_subscriptions
)


class TestVAPIDKeyHandling(unittest.TestCase):
    """Test VAPID key generation, conversion, and validation"""
    
    def test_create_notification_payload(self):
        """Test notification payload creation"""
        payload = create_notification_payload("Test Title", "Test Body", "/test-icon.png")
        
        self.assertEqual(payload['title'], "Test Title")
        self.assertEqual(payload['body'], "Test Body")
        self.assertEqual(payload['icon'], "/test-icon.png")
        self.assertEqual(payload['badge'], "/static/favicons/favicon-32x32.png")
        self.assertIn('timestamp', payload)
        self.assertIsInstance(payload['timestamp'], int)
    
    def test_create_notification_payload_defaults(self):
        """Test notification payload with default values"""
        payload = create_notification_payload("Title", "Body")
        
        self.assertEqual(payload['icon'], "/static/favicons/favicon-32x32.png")
        self.assertEqual(payload['badge'], "/static/favicons/favicon-32x32.png")
    
    def test_convert_pem_private_key_for_pywebpush_with_valid_pem(self):
        """Test conversion of valid PEM private key to Vapid instance"""
        # Generate a real VAPID key
        vapid = Vapid()
        vapid.generate_keys()
        private_pem = vapid.private_pem().decode()
        
        # Convert using our function
        converted_key = convert_pem_private_key_for_pywebpush(private_pem)
        
        # Should return a Vapid instance
        self.assertIsInstance(converted_key, Vapid)
    
    def test_convert_pem_private_key_invalid_input(self):
        """Test conversion with invalid input returns original"""
        invalid_key = "not-a-pem-key"
        result = convert_pem_private_key_for_pywebpush(invalid_key)
        self.assertEqual(result, invalid_key)
        
        none_key = None
        result = convert_pem_private_key_for_pywebpush(none_key)
        self.assertEqual(result, none_key)
    
    def test_convert_pem_public_key_for_browser(self):
        """Test conversion of PEM public key to browser format"""
        # Generate a real VAPID key pair
        vapid = Vapid()
        vapid.generate_keys()
        public_pem = vapid.public_pem().decode()
        
        # Convert to browser format
        browser_key = convert_pem_public_key_for_browser(public_pem)
        
        # Should return URL-safe base64 string
        self.assertIsInstance(browser_key, str)
        self.assertGreater(len(browser_key), 0)
        # Should not contain padding
        self.assertFalse(browser_key.endswith('='))
    
    def test_convert_pem_public_key_invalid(self):
        """Test public key conversion with invalid input"""
        result = convert_pem_public_key_for_browser("invalid-pem")
        self.assertIsNone(result)


class TestDatastoreIntegration(unittest.TestCase):
    """Test datastore operations for VAPID and subscriptions"""
    
    def test_get_vapid_config_from_datastore(self):
        """Test retrieving VAPID config from datastore"""
        mock_datastore = Mock()
        mock_datastore.data = {
            'settings': {
                'application': {
                    'vapid': {
                        'private_key': 'test-private-key',
                        'public_key': 'test-public-key',
                        'contact_email': 'test@example.com'
                    }
                }
            }
        }
        
        private_key, public_key, contact_email = get_vapid_config_from_datastore(mock_datastore)
        
        self.assertEqual(private_key, 'test-private-key')
        self.assertEqual(public_key, 'test-public-key')
        self.assertEqual(contact_email, 'test@example.com')
    
    def test_get_vapid_config_missing_email(self):
        """Test VAPID config with missing contact email uses default"""
        mock_datastore = Mock()
        mock_datastore.data = {
            'settings': {
                'application': {
                    'vapid': {
                        'private_key': 'test-private-key',
                        'public_key': 'test-public-key'
                    }
                }
            }
        }
        
        private_key, public_key, contact_email = get_vapid_config_from_datastore(mock_datastore)
        
        self.assertEqual(contact_email, 'citizen@example.com')
    
    def test_get_vapid_config_empty_datastore(self):
        """Test VAPID config with empty datastore returns None values"""
        mock_datastore = Mock()
        mock_datastore.data = {}
        
        private_key, public_key, contact_email = get_vapid_config_from_datastore(mock_datastore)
        
        self.assertIsNone(private_key)
        self.assertIsNone(public_key)
        self.assertEqual(contact_email, 'citizen@example.com')
    
    def test_get_browser_subscriptions(self):
        """Test retrieving browser subscriptions from datastore"""
        mock_datastore = Mock()
        test_subscriptions = [
            {
                'endpoint': 'https://fcm.googleapis.com/fcm/send/test1',
                'keys': {'p256dh': 'key1', 'auth': 'auth1'}
            },
            {
                'endpoint': 'https://fcm.googleapis.com/fcm/send/test2', 
                'keys': {'p256dh': 'key2', 'auth': 'auth2'}
            }
        ]
        mock_datastore.data = {
            'settings': {
                'application': {
                    'browser_subscriptions': test_subscriptions
                }
            }
        }
        
        subscriptions = get_browser_subscriptions(mock_datastore)
        
        self.assertEqual(len(subscriptions), 2)
        self.assertEqual(subscriptions, test_subscriptions)
    
    def test_get_browser_subscriptions_empty(self):
        """Test getting subscriptions from empty datastore returns empty list"""
        mock_datastore = Mock()
        mock_datastore.data = {}
        
        subscriptions = get_browser_subscriptions(mock_datastore)
        
        self.assertEqual(subscriptions, [])
    
    def test_save_browser_subscriptions(self):
        """Test saving browser subscriptions to datastore"""
        mock_datastore = Mock()
        mock_datastore.data = {'settings': {'application': {}}}
        
        test_subscriptions = [
            {'endpoint': 'test1', 'keys': {'p256dh': 'key1', 'auth': 'auth1'}}
        ]
        
        save_browser_subscriptions(mock_datastore, test_subscriptions)
        
        self.assertEqual(mock_datastore.data['settings']['application']['browser_subscriptions'], test_subscriptions)
        self.assertTrue(mock_datastore.needs_write)


class TestNotificationSending(unittest.TestCase):
    """Test notification sending with mocked pywebpush"""
    
    @patch('pywebpush.webpush')
    def test_send_push_notifications_success(self, mock_webpush):
        """Test successful notification sending"""
        mock_webpush.return_value = True
        
        mock_datastore = Mock()
        mock_datastore.needs_write = False
        
        subscriptions = [
            {
                'endpoint': 'https://fcm.googleapis.com/fcm/send/test1',
                'keys': {'p256dh': 'key1', 'auth': 'auth1'}
            }
        ]
        
        # Generate a real VAPID key for testing
        vapid = Vapid()
        vapid.generate_keys()
        private_key = vapid.private_pem().decode()
        
        notification_payload = {
            'title': 'Test Title',
            'body': 'Test Body'
        }
        
        success_count, total_count = send_push_notifications(
            subscriptions=subscriptions,
            notification_payload=notification_payload,
            private_key=private_key,
            contact_email='test@example.com',
            datastore=mock_datastore
        )
        
        self.assertEqual(success_count, 1)
        self.assertEqual(total_count, 1)
        self.assertTrue(mock_webpush.called)
        
        # Verify webpush was called with correct parameters
        call_args = mock_webpush.call_args
        self.assertEqual(call_args[1]['subscription_info'], subscriptions[0])
        self.assertEqual(json.loads(call_args[1]['data']), notification_payload)
        self.assertIn('vapid_private_key', call_args[1])
        self.assertEqual(call_args[1]['vapid_claims']['sub'], 'mailto:test@example.com')
    
    @patch('pywebpush.webpush')
    def test_send_push_notifications_webpush_exception(self, mock_webpush):
        """Test handling of WebPushException with invalid subscription removal"""
        from pywebpush import WebPushException
        
        # Mock a 410 response (subscription gone)
        mock_response = Mock()
        mock_response.status_code = 410
        
        mock_webpush.side_effect = WebPushException("Subscription expired", response=mock_response)
        
        mock_datastore = Mock()
        mock_datastore.needs_write = False
        
        subscriptions = [
            {
                'endpoint': 'https://fcm.googleapis.com/fcm/send/test1',
                'keys': {'p256dh': 'key1', 'auth': 'auth1'}
            }
        ]
        
        vapid = Vapid()
        vapid.generate_keys()
        private_key = vapid.private_pem().decode()
        
        success_count, total_count = send_push_notifications(
            subscriptions=subscriptions,
            notification_payload={'title': 'Test', 'body': 'Test'},
            private_key=private_key,
            contact_email='test@example.com',
            datastore=mock_datastore
        )
        
        self.assertEqual(success_count, 0)
        self.assertEqual(total_count, 1)
        self.assertTrue(mock_datastore.needs_write)  # Should mark for subscription cleanup
    
    def test_send_push_notifications_no_pywebpush(self):
        """Test graceful handling when pywebpush is not available"""
        with patch.dict('sys.modules', {'pywebpush': None}):
            subscriptions = [{'endpoint': 'test', 'keys': {}}]
            
            success_count, total_count = send_push_notifications(
                subscriptions=subscriptions,
                notification_payload={'title': 'Test', 'body': 'Test'},
                private_key='test-key',
                contact_email='test@example.com',
                datastore=Mock()
            )
            
            self.assertEqual(success_count, 0)
            self.assertEqual(total_count, 1)


class TestBrowserIntegration(unittest.TestCase):
    """Test browser integration aspects (file existence)"""
    
    def test_javascript_browser_notifications_class_exists(self):
        """Test that browser notifications JavaScript file exists and has expected structure"""
        js_file = "/var/www/changedetection.io/changedetectionio/static/js/browser-notifications.js"
        
        self.assertTrue(os.path.exists(js_file))
        
        with open(js_file, 'r') as f:
            content = f.read()
            
        # Check for key class and methods
        self.assertIn('class BrowserNotifications', content)
        self.assertIn('async init()', content)
        self.assertIn('async subscribe()', content)
        self.assertIn('async sendTestNotification()', content)
        self.assertIn('setupNotificationUrlMonitoring()', content)
    
    def test_service_worker_exists(self):
        """Test that service worker file exists"""
        sw_file = "/var/www/changedetection.io/changedetectionio/static/js/service-worker.js"
        
        self.assertTrue(os.path.exists(sw_file))
        
        with open(sw_file, 'r') as f:
            content = f.read()
            
        # Check for key service worker functionality
        self.assertIn('push', content)
        self.assertIn('notificationclick', content)


class TestAPIEndpoints(unittest.TestCase):
    """Test browser notification API endpoints"""
    
    def test_browser_notifications_module_exists(self):
        """Test that BrowserNotifications API module exists"""
        api_file = "/var/www/changedetection.io/changedetectionio/notification/BrowserNotifications.py"
        
        self.assertTrue(os.path.exists(api_file))
        
        with open(api_file, 'r') as f:
            content = f.read()
            
        # Check for key API classes
        self.assertIn('BrowserNotificationsVapidPublicKey', content)
        self.assertIn('BrowserNotificationsSubscribe', content)  
        self.assertIn('BrowserNotificationsUnsubscribe', content)
    
    def test_vapid_public_key_conversion(self):
        """Test VAPID public key conversion for browser use"""
        # Generate a real key pair
        vapid = Vapid()
        vapid.generate_keys()
        public_pem = vapid.public_pem().decode()
        
        # Convert to browser format
        browser_key = convert_pem_public_key_for_browser(public_pem)
        
        # Verify it's a valid URL-safe base64 string
        self.assertIsInstance(browser_key, str)
        self.assertGreater(len(browser_key), 80)  # P-256 uncompressed point should be ~88 chars
        
        # Should not have padding
        self.assertFalse(browser_key.endswith('='))
        
        # Should only contain URL-safe base64 characters
        import re
        self.assertRegex(browser_key, r'^[A-Za-z0-9_-]+$')


class TestIntegrationFlow(unittest.TestCase):
    """Test complete integration flow"""
    
    @patch('pywebpush.webpush')
    def test_complete_notification_flow(self, mock_webpush):
        """Test complete flow from subscription to notification"""
        mock_webpush.return_value = True
        
        # Create mock datastore with VAPID keys
        mock_datastore = Mock()
        vapid = Vapid()
        vapid.generate_keys()
        
        mock_datastore.data = {
            'settings': {
                'application': {
                    'vapid': {
                        'private_key': vapid.private_pem().decode(),
                        'public_key': vapid.public_pem().decode(),
                        'contact_email': 'test@example.com'
                    },
                    'browser_subscriptions': [
                        {
                            'endpoint': 'https://fcm.googleapis.com/fcm/send/test123',
                            'keys': {
                                'p256dh': 'test-p256dh-key',
                                'auth': 'test-auth-key'
                            }
                        }
                    ]
                }
            }
        }
        mock_datastore.needs_write = False
        
        # Get configuration
        private_key, public_key, contact_email = get_vapid_config_from_datastore(mock_datastore)
        subscriptions = get_browser_subscriptions(mock_datastore)
        
        # Create notification
        payload = create_notification_payload("Test Title", "Test Message")
        
        # Send notification
        success_count, total_count = send_push_notifications(
            subscriptions=subscriptions,
            notification_payload=payload,
            private_key=private_key,
            contact_email=contact_email,
            datastore=mock_datastore
        )
        
        # Verify success
        self.assertEqual(success_count, 1)
        self.assertEqual(total_count, 1)
        self.assertTrue(mock_webpush.called)
        
        # Verify webpush call parameters
        call_args = mock_webpush.call_args
        self.assertIn('subscription_info', call_args[1])
        self.assertIn('vapid_private_key', call_args[1])
        self.assertIn('vapid_claims', call_args[1])
        
        # Verify vapid_claims format
        vapid_claims = call_args[1]['vapid_claims']
        self.assertEqual(vapid_claims['sub'], 'mailto:test@example.com')
        self.assertEqual(vapid_claims['aud'], 'https://fcm.googleapis.com')


if __name__ == '__main__':
    unittest.main()