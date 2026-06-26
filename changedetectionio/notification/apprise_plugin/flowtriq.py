"""
Custom Flowtriq notification plugin for changedetection.io

Sends structured webhook payloads to Flowtriq (https://flowtriq.com) for
correlating website changes and outages with DDoS attack data.

Usage:
    flowtriq://{hostname}/{path}
    flowtriq://{hostname}/{path}?key={api_key}

Examples:
    flowtriq://app.flowtriq.com/api/v1/webhooks/changedetection
    flowtriq://app.flowtriq.com/api/v1/webhooks/changedetection?key=your-api-key

The plugin POSTs a JSON payload containing:
    - source: "changedetection"
    - watch_url: the URL being monitored
    - title: notification title
    - body: notification body (change details / diff)
    - status: "change_detected"
"""

import json

import requests
from apprise import NotifyBase, NotifyType
from apprise.common import NotifyFormat
from loguru import logger


class NotifyFlowtriq(NotifyBase):
    """
    Flowtriq webhook notification plugin.
    """

    app_id = 'NotifyFlowtriq'
    app_desc = 'Flowtriq DDoS Detection & Traffic Analytics'
    default_port = 443
    default_secure_protocol = 'flowtriq'
    notify_url_prefix = 'https'

    # Plugin identification
    protocol = 'flowtriq'
    secure_protocol = 'flowtriq'
    notify_format = NotifyFormat.TEXT

    # Title is not used in the JSON payload structure directly,
    # but we accept it for compatibility
    title_maxlen = 250

    def __init__(self, apikey=None, **kwargs):
        super().__init__(**kwargs)

        # API key for X-API-Key header (optional)
        self.apikey = apikey

        # Build the webhook URL from the parsed components
        schema = 'https'
        self.webhook_url = f'{schema}://{self.host}'

        if self.port and self.port != 443:
            self.webhook_url += f':{self.port}'

        if self.fullpath:
            self.webhook_url += self.fullpath

        return

    def send(self, body, title='', notify_type=NotifyType.INFO, **kwargs):
        """
        Send a structured JSON payload to the Flowtriq webhook endpoint.
        """
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'changedetection.io',
        }

        if self.apikey:
            headers['X-API-Key'] = self.apikey

        payload = {
            'source': 'changedetection',
            'watch_url': title,
            'title': title,
            'body': body,
            'status': 'change_detected',
        }

        logger.info(f'Sending Flowtriq notification to {self.webhook_url}')

        try:
            response = requests.post(
                self.webhook_url,
                data=json.dumps(payload),
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()

        except requests.RequestException as e:
            logger.warning(f'Flowtriq notification failed: {e}')
            return False

        logger.info(f'Flowtriq notification sent successfully to {self.webhook_url}')
        return True

    def url(self, privacy=False, *args, **kwargs):
        """
        Return the URL representation of this notification.
        """
        default_port = 443

        url = '{schema}://{hostname}{port}{path}?key={apikey}'.format(
            schema=self.protocol,
            hostname=self.host,
            port='' if not self.port or self.port == default_port
            else f':{self.port}',
            path=self.fullpath if self.fullpath else '',
            apikey=self.pprint(self.apikey, 'key', safe='')
            if self.apikey else '',
        )

        # Remove trailing ?key= when no API key is set
        url = url.rstrip('?key=')

        return url

    @staticmethod
    def parse_url(url):
        """
        Parse the Flowtriq URL and return the components needed to
        re-instantiate this plugin.
        """
        results = NotifyBase.parse_url(url, verify_host=True)
        if not results:
            return results

        # Extract API key from ?key= query parameter
        results['apikey'] = results['qsd'].get('key')

        return results
