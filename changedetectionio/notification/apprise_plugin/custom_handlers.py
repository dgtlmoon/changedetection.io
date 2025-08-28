import json
import re
import time
from urllib.parse import unquote_plus

import requests
from apprise.decorators import notify
from apprise.utils.parse import parse_url as apprise_parse_url
from loguru import logger
from requests.structures import CaseInsensitiveDict

SUPPORTED_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head"}


def notify_supported_methods(func):
    for method in SUPPORTED_HTTP_METHODS:
        func = notify(on=method)(func)
        # Add support for https, for each supported http method
        func = notify(on=f"{method}s")(func)
    return func


def _get_auth(parsed_url: dict) -> str | tuple[str, str]:
    user: str | None = parsed_url.get("user")
    password: str | None = parsed_url.get("password")

    if user is not None and password is not None:
        return (unquote_plus(user), unquote_plus(password))

    if user is not None:
        return unquote_plus(user)

    return ""


def _get_headers(parsed_url: dict, body: str) -> CaseInsensitiveDict:
    headers = CaseInsensitiveDict(
        {unquote_plus(k).title(): unquote_plus(v) for k, v in parsed_url["qsd+"].items()}
    )

    # If Content-Type is not specified, guess if the body is a valid JSON
    if headers.get("Content-Type") is None:
        try:
            json.loads(body)
            headers["Content-Type"] = "application/json; charset=utf-8"
        except Exception:
            pass

    return headers


def _get_params(parsed_url: dict) -> CaseInsensitiveDict:
    # https://github.com/caronc/apprise/wiki/Notify_Custom_JSON#get-parameter-manipulation
    # In Apprise, it relies on prefixing each request arg with "-", because it uses say &method=update as a flag for apprise
    # but here we are making straight requests, so we need todo convert this against apprise's logic
    params = CaseInsensitiveDict(
        {
            unquote_plus(k): unquote_plus(v)
            for k, v in parsed_url["qsd"].items()
            if k.strip("-") not in parsed_url["qsd-"]
            and k.strip("+") not in parsed_url["qsd+"]
        }
    )

    return params


@notify_supported_methods
def apprise_http_custom_handler(
    body: str,
    title: str,
    notify_type: str,
    meta: dict,
    *args,
    **kwargs,
) -> bool:
    url: str = meta.get("url")
    schema: str = meta.get("schema")
    method: str = re.sub(r"s$", "", schema).upper()

    # Convert /foobar?+some-header=hello to proper header dictionary
    parsed_url: dict[str, str | dict | None] | None = apprise_parse_url(url)
    if parsed_url is None:
        return False

    auth = _get_auth(parsed_url=parsed_url)
    headers = _get_headers(parsed_url=parsed_url, body=body)
    params = _get_params(parsed_url=parsed_url)

    url = re.sub(rf"^{schema}", "https" if schema.endswith("s") else "http", parsed_url.get("url"))

    try:
        response = requests.request(
            method=method,
            url=url,
            auth=auth,
            headers=headers,
            params=params,
            data=body.encode("utf-8") if isinstance(body, str) else body,
        )

        response.raise_for_status()

        logger.info(f"Successfully sent custom notification to {url}")
        return True

    except requests.RequestException as e:
        logger.error(f"Remote host error while sending custom notification to {url}: {e}")
        return False

    except Exception as e:
        logger.error(f"Unexpected error occurred while sending custom notification to {url}: {e}")
        return False


@notify(on="browser")
def apprise_browser_notification_handler(
    body: str,
    title: str,
    notify_type: str,
    meta: dict,
    *args,
    **kwargs,
) -> bool:
    """
    Browser push notification handler for browser:// URLs
    Format: browser://keyword where keyword is the namespace for subscriptions
    """
    try:
        from pywebpush import webpush, WebPushException
        from flask import current_app
        
        url: str = meta.get("url")
        parsed_url = apprise_parse_url(url)
        
        if not parsed_url:
            logger.error("Failed to parse browser notification URL")
            return False
            
        # Extract keyword from URL - format is browser://keyword
        keyword = parsed_url.get('host', 'default')
        
        # Get VAPID keys from app settings
        try:
            datastore = current_app.config.get('DATASTORE')
            if not datastore:
                logger.error("No datastore available for browser notifications")
                return False
                
            vapid_config = datastore.data.get('settings', {}).get('application', {}).get('vapid', {})
            private_key = vapid_config.get('private_key')
            public_key = vapid_config.get('public_key')
            contact_email = vapid_config.get('contact_email', 'admin@changedetection.io')
            
            if not private_key or not public_key:
                logger.error("VAPID keys not configured for browser notifications")
                return False
                
        except Exception as e:
            logger.error(f"Failed to get VAPID configuration: {e}")
            return False
        
        # Get subscriptions for this keyword from datastore
        browser_subscriptions = datastore.data.get('browser_subscriptions', {}).get(keyword, [])
        
        if not browser_subscriptions:
            logger.info(f"No browser subscriptions found for keyword: {keyword}")
            return True  # Not an error - just no subscribers
            
        # Import helper functions
        try:
            from .browser_notification_helpers import create_notification_payload, send_push_notifications
        except ImportError:
            logger.error("Browser notification helpers not available")
            return False
        
        # Prepare notification payload
        notification_payload = create_notification_payload(title, body)
        
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
        if keyword not in datastore.data.get('browser_subscriptions', {}):
            if 'browser_subscriptions' not in datastore.data:
                datastore.data['browser_subscriptions'] = {}
            datastore.data['browser_subscriptions'][keyword] = []
        datastore.data['browser_subscriptions'][keyword] = browser_subscriptions
        
        logger.info(f"Sent browser notifications: {success_count}/{total_count} successful for keyword '{keyword}'")
        return success_count > 0
        
    except ImportError:
        logger.error("pywebpush not available - cannot send browser notifications")
        return False
    except Exception as e:
        logger.error(f"Unexpected error in browser notification handler: {e}")
        return False
