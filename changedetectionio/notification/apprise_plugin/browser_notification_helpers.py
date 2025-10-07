"""
Browser notification helpers for Web Push API
Shared utility functions for VAPID key handling and notification sending
"""

import json
import re
import time
from loguru import logger


def convert_pem_private_key_for_pywebpush(private_key):
    """
    Convert PEM private key to the format that pywebpush expects
    
    Args:
        private_key: PEM private key string or already converted key
        
    Returns:
        Vapid instance for pywebpush (avoids PEM parsing compatibility issues)
    """
    try:
        from py_vapid import Vapid
        import tempfile
        import os
        
        # If we get a string, assume it's PEM and create a Vapid instance from it
        if isinstance(private_key, str) and private_key.startswith('-----BEGIN'):
            # Write PEM to temporary file and load with Vapid.from_file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.pem', delete=False) as tmp_file:
                tmp_file.write(private_key)
                tmp_file.flush()
                temp_path = tmp_file.name
                
            try:
                # Load using Vapid.from_file - this is more compatible with pywebpush
                vapid_instance = Vapid.from_file(temp_path)
                os.unlink(temp_path)  # Clean up
                logger.debug("Successfully created Vapid instance from PEM")
                return vapid_instance
            except Exception as e:
                os.unlink(temp_path)  # Clean up even on error
                logger.error(f"Failed to create Vapid instance from PEM: {e}")
                # Fall back to returning the original PEM string
                return private_key
        else:
            # Return as-is if not a PEM string  
            return private_key
            
    except Exception as e:
        logger.error(f"Failed to convert private key: {e}")
        return private_key


def convert_pem_public_key_for_browser(public_key_pem):
    """
    Convert PEM public key to URL-safe base64 format for browser applicationServerKey
    
    Args:
        public_key_pem: PEM public key string
        
    Returns:
        URL-safe base64 encoded public key without padding
    """
    try:
        from cryptography.hazmat.primitives import serialization
        import base64
        
        # Parse PEM directly using cryptography library
        pem_bytes = public_key_pem.encode() if isinstance(public_key_pem, str) else public_key_pem
        
        # Load the public key from PEM
        public_key_crypto = serialization.load_pem_public_key(pem_bytes)
        
        # Get the raw public key bytes in uncompressed format (what browsers expect)
        public_key_raw = public_key_crypto.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint
        )
        
        # Convert to URL-safe base64 (remove padding)
        public_key_b64 = base64.urlsafe_b64encode(public_key_raw).decode('ascii').rstrip('=')
        
        return public_key_b64
        
    except Exception as e:
        logger.error(f"Failed to convert public key format: {e}")
        return None


def send_push_notifications(subscriptions, notification_payload, private_key, contact_email, datastore):
    """
    Send push notifications to a list of subscriptions
    
    Args:
        subscriptions: List of push subscriptions
        notification_payload: Dict with notification data (title, body, etc.)
        private_key: VAPID private key (will be converted if needed)
        contact_email: Contact email for VAPID claims
        datastore: Datastore object for updating subscriptions
        
    Returns:
        Tuple of (success_count, total_count)
    """
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        logger.error("pywebpush not available - cannot send browser notifications")
        return 0, len(subscriptions)
    
    # Convert private key to format pywebpush expects
    private_key_for_push = convert_pem_private_key_for_pywebpush(private_key)
    
    success_count = 0
    total_count = len(subscriptions)
    
    # Send to all subscriptions
    for subscription in subscriptions[:]:  # Copy list to avoid modification issues
        try:
            webpush(
                subscription_info=subscription,
                data=json.dumps(notification_payload),
                vapid_private_key=private_key_for_push,
                vapid_claims={
                    "sub": f"mailto:{contact_email}",
                    "aud": f"https://{subscription['endpoint'].split('/')[2]}"
                }
            )
            success_count += 1
            
        except WebPushException as e:
            logger.warning(f"Failed to send browser notification to subscription: {e}")
            # Remove invalid subscriptions (410 = Gone, 404 = Not Found)
            if e.response and e.response.status_code in [404, 410]:
                logger.info("Removing invalid browser notification subscription")
                try:
                    subscriptions.remove(subscription)
                    datastore.needs_write = True
                except ValueError:
                    pass  # Already removed
                    
        except Exception as e:
            logger.error(f"Unexpected error sending browser notification: {e}")
    
    return success_count, total_count


def create_notification_payload(title, body, icon_path=None):
    """
    Create a standard notification payload
    
    Args:
        title: Notification title
        body: Notification body
        icon_path: Optional icon path (defaults to favicon)
        
    Returns:
        Dict with notification payload
    """
    return {
        'title': title,
        'body': body,
        'icon': icon_path or '/static/favicons/favicon-32x32.png',
        'badge': '/static/favicons/favicon-32x32.png',
        'timestamp': int(time.time() * 1000),
    }


def get_vapid_config_from_datastore(datastore):
    """
    Get VAPID configuration from datastore with proper error handling
    
    Args:
        datastore: Datastore object
        
    Returns:
        Tuple of (private_key, public_key, contact_email) or (None, None, None) if error
    """
    try:
        if not datastore:
            return None, None, None
            
        vapid_config = datastore.data.get('settings', {}).get('application', {}).get('vapid', {})
        private_key = vapid_config.get('private_key')
        public_key = vapid_config.get('public_key')
        contact_email = vapid_config.get('contact_email', 'citizen@example.com')
        
        return private_key, public_key, contact_email
        
    except Exception as e:
        logger.error(f"Failed to get VAPID config from datastore: {e}")
        return None, None, None



def get_browser_subscriptions(datastore):
    """
    Get browser subscriptions from datastore
    
    Args:
        datastore: Datastore object
        
    Returns:
        List of subscriptions
    """
    try:
        if not datastore:
            return []
            
        return datastore.data.get('settings', {}).get('application', {}).get('browser_subscriptions', [])
        
    except Exception as e:
        logger.error(f"Failed to get browser subscriptions: {e}")
        return []


def save_browser_subscriptions(datastore, subscriptions):
    """
    Save browser subscriptions to datastore
    
    Args:
        datastore: Datastore object
        subscriptions: List of subscriptions to save
    """
    try:
        if not datastore:
            return
            
        # Ensure the settings structure exists
        if 'settings' not in datastore.data:
            datastore.data['settings'] = {}
        if 'application' not in datastore.data['settings']:
            datastore.data['settings']['application'] = {}
            
        datastore.data['settings']['application']['browser_subscriptions'] = subscriptions
        datastore.needs_write = True
        
    except Exception as e:
        logger.error(f"Failed to save browser subscriptions: {e}")




def create_error_response(message, sent_count=0, status_code=500):
    """
    Create standardized error response for API endpoints
    
    Args:
        message: Error message
        sent_count: Number of notifications sent (for test endpoints)
        status_code: HTTP status code
        
    Returns:
        Tuple of (response_dict, status_code)
    """
    return {'success': False, 'message': message, 'sent_count': sent_count}, status_code


def create_success_response(message, sent_count=None):
    """
    Create standardized success response for API endpoints
    
    Args:
        message: Success message
        sent_count: Number of notifications sent (optional)
        
    Returns:
        Response dict
    """
    response = {'success': True, 'message': message}
    if sent_count is not None:
        response['sent_count'] = sent_count
    return response