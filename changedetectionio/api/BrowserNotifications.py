import json
from flask import request, current_app
from flask_restful import Resource, marshal_with, fields
from changedetectionio.api import validate_openapi_request
from loguru import logger


browser_notifications_fields = {
    'success': fields.Boolean,
    'message': fields.String,
}

vapid_public_key_fields = {
    'publicKey': fields.String,
}

test_notification_fields = {
    'success': fields.Boolean,
    'message': fields.String,
    'sent_count': fields.Integer,
}


class BrowserNotificationsVapidPublicKey(Resource):
    """Get VAPID public key for browser push notifications"""
    
    @marshal_with(vapid_public_key_fields)
    def get(self):
        try:
            from changedetectionio.notification.apprise_plugin.browser_notification_helpers import (
                get_vapid_config_from_datastore, convert_pem_public_key_for_browser
            )
            
            datastore = current_app.config.get('DATASTORE')
            if not datastore:
                return {'publicKey': None}, 500
                
            private_key, public_key_pem, contact_email = get_vapid_config_from_datastore(datastore)
            
            if not public_key_pem:
                return {'publicKey': None}, 404
            
            # Convert PEM format to URL-safe base64 format for browser
            public_key_b64 = convert_pem_public_key_for_browser(public_key_pem)
            
            if public_key_b64:
                return {'publicKey': public_key_b64}
            else:
                return {'publicKey': None}, 500
                
        except Exception as e:
            logger.error(f"Failed to get VAPID public key: {e}")
            return {'publicKey': None}, 500


class BrowserNotificationsSubscribe(Resource):
    """Subscribe to browser notifications for a keyword"""
    
    @marshal_with(browser_notifications_fields)
    def post(self):
        try:
            data = request.get_json()
            if not data:
                return {'success': False, 'message': 'No data provided'}, 400
                
            keyword = data.get('keyword', '').strip()
            subscription = data.get('subscription')
            
            if not keyword:
                return {'success': False, 'message': 'Keyword is required'}, 400
                
            if not subscription:
                return {'success': False, 'message': 'Subscription is required'}, 400
                
            # Validate subscription format
            required_fields = ['endpoint', 'keys']
            for field in required_fields:
                if field not in subscription:
                    return {'success': False, 'message': f'Missing subscription field: {field}'}, 400
                    
            if 'p256dh' not in subscription['keys'] or 'auth' not in subscription['keys']:
                return {'success': False, 'message': 'Missing subscription keys'}, 400
                
            # Get datastore
            datastore = current_app.config.get('DATASTORE')
            if not datastore:
                return {'success': False, 'message': 'Datastore not available'}, 500
                
            # Initialize browser_subscriptions if it doesn't exist
            if 'browser_subscriptions' not in datastore.data:
                datastore.data['browser_subscriptions'] = {}
                
            if keyword not in datastore.data['browser_subscriptions']:
                datastore.data['browser_subscriptions'][keyword] = []
                
            # Check if subscription already exists
            existing_subscriptions = datastore.data['browser_subscriptions'][keyword]
            for existing_sub in existing_subscriptions:
                if existing_sub.get('endpoint') == subscription.get('endpoint'):
                    return {'success': True, 'message': f'Already subscribed to {keyword}'}
                    
            # Add new subscription
            datastore.data['browser_subscriptions'][keyword].append(subscription)
            datastore.needs_write = True
            
            logger.info(f"New browser notification subscription for keyword '{keyword}': {subscription.get('endpoint')}")
            
            return {'success': True, 'message': f'Successfully subscribed to {keyword}'}
            
        except Exception as e:
            logger.error(f"Failed to subscribe to browser notifications: {e}")
            return {'success': False, 'message': f'Subscription failed: {str(e)}'}, 500


class BrowserNotificationsUnsubscribe(Resource):
    """Unsubscribe from browser notifications for a keyword"""
    
    @marshal_with(browser_notifications_fields)
    def post(self):
        try:
            data = request.get_json()
            if not data:
                return {'success': False, 'message': 'No data provided'}, 400
                
            keyword = data.get('keyword', '').strip()
            subscription = data.get('subscription')
            
            if not keyword:
                return {'success': False, 'message': 'Keyword is required'}, 400
                
            if not subscription or not subscription.get('endpoint'):
                return {'success': False, 'message': 'Valid subscription is required'}, 400
                
            # Get datastore
            datastore = current_app.config.get('DATASTORE')
            if not datastore:
                return {'success': False, 'message': 'Datastore not available'}, 500
                
            # Check if subscriptions exist for this keyword
            browser_subscriptions = datastore.data.get('browser_subscriptions', {})
            if keyword not in browser_subscriptions:
                return {'success': True, 'message': f'No subscriptions found for {keyword}'}
                
            # Remove subscription with matching endpoint
            endpoint = subscription.get('endpoint')
            subscriptions = browser_subscriptions[keyword]
            original_count = len(subscriptions)
            
            browser_subscriptions[keyword] = [
                sub for sub in subscriptions 
                if sub.get('endpoint') != endpoint
            ]
            
            removed_count = original_count - len(browser_subscriptions[keyword])
            
            if removed_count > 0:
                datastore.needs_write = True
                logger.info(f"Removed {removed_count} browser notification subscription(s) for keyword '{keyword}'")
                return {'success': True, 'message': f'Successfully unsubscribed from {keyword}'}
            else:
                return {'success': True, 'message': f'No matching subscription found for {keyword}'}
                
        except Exception as e:
            logger.error(f"Failed to unsubscribe from browser notifications: {e}")
            return {'success': False, 'message': f'Unsubscribe failed: {str(e)}'}, 500


class BrowserNotificationsTest(Resource):
    """Send a test browser notification"""
    
    @marshal_with(test_notification_fields)
    def post(self):
        try:
            data = request.get_json()
            if not data:
                return {'success': False, 'message': 'No data provided', 'sent_count': 0}, 400
                
            keyword = data.get('keyword', 'default').strip()
            title = data.get('title', 'Test Notification')
            body = data.get('body', 'This is a test notification from changedetection.io')
            
            # Get datastore
            datastore = current_app.config.get('DATASTORE')
            if not datastore:
                return {'success': False, 'message': 'Datastore not available', 'sent_count': 0}, 500
                
            # Check VAPID configuration
            vapid_config = datastore.data.get('settings', {}).get('application', {}).get('vapid', {})
            if not vapid_config.get('private_key') or not vapid_config.get('public_key'):
                return {'success': False, 'message': 'VAPID keys not configured', 'sent_count': 0}, 500
                
            # Check if there are subscriptions for this keyword
            browser_subscriptions = datastore.data.get('browser_subscriptions', {}).get(keyword, [])
            if not browser_subscriptions:
                return {'success': False, 'message': f'No subscriptions found for keyword: {keyword}', 'sent_count': 0}, 404
                
            # Import and send notifications using the custom handler
            try:
                from pywebpush import webpush, WebPushException
                import time
                
                # Import helper functions
                try:
                    from changedetectionio.notification.apprise_plugin.browser_notification_helpers import create_notification_payload, send_push_notifications
                except ImportError:
                    return {'success': False, 'message': 'Browser notification helpers not available', 'sent_count': 0}, 500
                
                # Prepare notification payload
                notification_payload = create_notification_payload(title, body)
                
                private_key = vapid_config.get('private_key')
                contact_email = vapid_config.get('contact_email', 'admin@changedetection.io')
                
                # Send notifications using shared helper
                success_count, total_count = send_push_notifications(
                    subscriptions=browser_subscriptions,
                    notification_payload=notification_payload,
                    private_key=private_key,
                    contact_email=contact_email,
                    keyword=keyword,
                    datastore=datastore
                )
                
                # Update datastore with cleaned subscriptions
                datastore.data['browser_subscriptions'][keyword] = browser_subscriptions
                
                if success_count > 0:
                    return {
                        'success': True, 
                        'message': f'Test notification sent successfully to {success_count} subscriber(s)',
                        'sent_count': success_count
                    }
                else:
                    return {
                        'success': False, 
                        'message': 'Failed to send test notification to any subscribers',
                        'sent_count': 0
                    }, 500
                    
            except ImportError:
                return {'success': False, 'message': 'pywebpush not available', 'sent_count': 0}, 500
                
        except Exception as e:
            logger.error(f"Failed to send test browser notification: {e}")
            return {'success': False, 'message': f'Test failed: {str(e)}', 'sent_count': 0}, 500


class BrowserNotificationsSubscriptions(Resource):
    """Get all browser notification subscriptions (for debugging/admin)"""
    
    def get(self):
        try:
            datastore = current_app.config.get('DATASTORE')
            if not datastore:
                return {'subscriptions': {}}, 500
                
            browser_subscriptions = datastore.data.get('browser_subscriptions', {})
            
            # Return summary without sensitive data
            summary = {}
            for keyword, subscriptions in browser_subscriptions.items():
                summary[keyword] = {
                    'count': len(subscriptions),
                    'endpoints': [sub.get('endpoint', 'unknown')[-50:] for sub in subscriptions]  # Last 50 chars
                }
                
            return {'subscriptions': summary}
            
        except Exception as e:
            logger.error(f"Failed to get browser notification subscriptions: {e}")
            return {'subscriptions': {}, 'error': str(e)}, 500


class BrowserNotificationsPendingKeywords(Resource):
    """Get pending keywords from session (after form submission)"""
    
    def get(self):
        try:
            from flask import session
            
            # Get keywords from session and clear them
            keywords = session.pop('browser_notification_keywords', [])
            
            return {'keywords': keywords}
            
        except Exception as e:
            logger.error(f"Failed to get pending browser notification keywords: {e}")
            return {'keywords': [], 'error': str(e)}, 500