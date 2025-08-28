import json
from flask import request, current_app
from flask_restful import Resource, marshal_with, fields
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
    """Subscribe to browser notifications"""
    
    @marshal_with(browser_notifications_fields)
    def post(self):
        try:
            data = request.get_json()
            if not data:
                return {'success': False, 'message': 'No data provided'}, 400
                
            subscription = data.get('subscription')
            
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
            if 'browser_subscriptions' not in datastore.data['settings']['application']:
                datastore.data['settings']['application']['browser_subscriptions'] = []
                
            # Check if subscription already exists
            existing_subscriptions = datastore.data['settings']['application']['browser_subscriptions']
            for existing_sub in existing_subscriptions:
                if existing_sub.get('endpoint') == subscription.get('endpoint'):
                    return {'success': True, 'message': 'Already subscribed to browser notifications'}
                    
            # Add new subscription
            datastore.data['settings']['application']['browser_subscriptions'].append(subscription)
            datastore.needs_write = True
            
            logger.info(f"New browser notification subscription: {subscription.get('endpoint')}")
            
            return {'success': True, 'message': 'Successfully subscribed to browser notifications'}
            
        except Exception as e:
            logger.error(f"Failed to subscribe to browser notifications: {e}")
            return {'success': False, 'message': f'Subscription failed: {str(e)}'}, 500


class BrowserNotificationsUnsubscribe(Resource):
    """Unsubscribe from browser notifications"""
    
    @marshal_with(browser_notifications_fields)
    def post(self):
        try:
            data = request.get_json()
            if not data:
                return {'success': False, 'message': 'No data provided'}, 400
                
            subscription = data.get('subscription')
            
            if not subscription or not subscription.get('endpoint'):
                return {'success': False, 'message': 'Valid subscription is required'}, 400
                
            # Get datastore
            datastore = current_app.config.get('DATASTORE')
            if not datastore:
                return {'success': False, 'message': 'Datastore not available'}, 500
                
            # Check if subscriptions exist
            browser_subscriptions = datastore.data.get('settings', {}).get('application', {}).get('browser_subscriptions', [])
            if not browser_subscriptions:
                return {'success': True, 'message': 'No subscriptions found'}
                
            # Remove subscription with matching endpoint
            endpoint = subscription.get('endpoint')
            original_count = len(browser_subscriptions)
            
            datastore.data['settings']['application']['browser_subscriptions'] = [
                sub for sub in browser_subscriptions 
                if sub.get('endpoint') != endpoint
            ]
            
            removed_count = original_count - len(datastore.data['settings']['application']['browser_subscriptions'])
            
            if removed_count > 0:
                datastore.needs_write = True
                logger.info(f"Removed {removed_count} browser notification subscription(s)")
                return {'success': True, 'message': 'Successfully unsubscribed from browser notifications'}
            else:
                return {'success': True, 'message': 'No matching subscription found'}
                
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
                
            title = data.get('title', 'Test Notification')
            body = data.get('body', 'This is a test notification from changedetection.io')
            
            # Get datastore to check if subscriptions exist
            datastore = current_app.config.get('DATASTORE')
            if not datastore:
                return {'success': False, 'message': 'Datastore not available', 'sent_count': 0}, 500
                
            # Check if there are subscriptions before attempting to send
            browser_subscriptions = datastore.data.get('settings', {}).get('application', {}).get('browser_subscriptions', [])
            if not browser_subscriptions:
                return {'success': False, 'message': 'No subscriptions found', 'sent_count': 0}, 404
            
            # Use the apprise handler directly
            try:
                from changedetectionio.notification.apprise_plugin.custom_handlers import apprise_browser_notification_handler
                
                # Call the apprise handler with test data
                success = apprise_browser_notification_handler(
                    body=body,
                    title=title,
                    notify_type='info',
                    meta={'url': 'browser://test'}
                )
                
                # Count how many subscriptions we have after sending (some may have been removed if invalid)
                final_subscriptions = datastore.data.get('settings', {}).get('application', {}).get('browser_subscriptions', [])
                sent_count = len(browser_subscriptions)  # Original count
                
                if success:
                    return {
                        'success': True,
                        'message': f'Test notification sent successfully to {sent_count} subscriber(s)',
                        'sent_count': sent_count
                    }
                else:
                    return {
                        'success': False,
                        'message': 'Failed to send test notification',
                        'sent_count': 0
                    }, 500
                    
            except ImportError:
                return {'success': False, 'message': 'Browser notification handler not available', 'sent_count': 0}, 500
                
        except Exception as e:
            logger.error(f"Failed to send test browser notification: {e}")
            return {'success': False, 'message': f'Test failed: {str(e)}', 'sent_count': 0}, 500




