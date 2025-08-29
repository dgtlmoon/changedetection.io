from flask import Blueprint, jsonify, request
from loguru import logger


def construct_blueprint(datastore):
    browser_notifications_blueprint = Blueprint('browser_notifications', __name__)

    @browser_notifications_blueprint.route("/test", methods=['POST'])
    def test_browser_notification():
        """Send a test browser notification using the apprise handler"""
        try:
            from changedetectionio.notification.apprise_plugin.custom_handlers import apprise_browser_notification_handler
            
            # Check if there are any subscriptions
            browser_subscriptions = datastore.data.get('settings', {}).get('application', {}).get('browser_subscriptions', [])
            if not browser_subscriptions:
                return jsonify({'success': False, 'message': 'No browser subscriptions found'}), 404
            
            # Get notification data from request or use defaults
            data = request.get_json() or {}
            title = data.get('title', 'Test Notification')
            body = data.get('body', 'This is a test notification from changedetection.io')
            
            # Use the apprise handler directly
            success = apprise_browser_notification_handler(
                body=body,
                title=title,
                notify_type='info',
                meta={'url': 'browser://test'}
            )
            
            if success:
                subscription_count = len(browser_subscriptions)
                return jsonify({
                    'success': True,
                    'message': f'Test notification sent successfully to {subscription_count} subscriber(s)'
                })
            else:
                return jsonify({'success': False, 'message': 'Failed to send test notification'}), 500
                
        except ImportError:
            logger.error("Browser notification handler not available")
            return jsonify({'success': False, 'message': 'Browser notification handler not available'}), 500
        except Exception as e:
            logger.error(f"Failed to send test browser notification: {e}")
            return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500

    @browser_notifications_blueprint.route("/clear", methods=['POST'])
    def clear_all_browser_notifications():
        """Clear all browser notification subscriptions from the datastore"""
        try:
            # Get current subscription count
            browser_subscriptions = datastore.data.get('settings', {}).get('application', {}).get('browser_subscriptions', [])
            subscription_count = len(browser_subscriptions)
            
            # Clear all subscriptions
            if 'settings' not in datastore.data:
                datastore.data['settings'] = {}
            if 'application' not in datastore.data['settings']:
                datastore.data['settings']['application'] = {}
                
            datastore.data['settings']['application']['browser_subscriptions'] = []
            datastore.needs_write = True
            
            logger.info(f"Cleared {subscription_count} browser notification subscriptions")
            
            return jsonify({
                'success': True, 
                'message': f'Cleared {subscription_count} browser notification subscription(s)'
            })
            
        except Exception as e:
            logger.error(f"Failed to clear all browser notifications: {e}")
            return jsonify({'success': False, 'message': f'Clear all failed: {str(e)}'}), 500

    return browser_notifications_blueprint