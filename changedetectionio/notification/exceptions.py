"""
Notification module exceptions
"""


class AppriseNotificationException(Exception):
    """
    Exception raised when Apprise notification fails to send (network, authentication, etc).

    These are transient failures that should be retried with exponential backoff.

    Includes the fully rendered notification content (sent_objs) that was attempted,
    so we can show exactly what failed even when the send doesn't succeed.

    Attributes:
        sent_objs: List of rendered notification objects with title, body, url
    """
    def __init__(self, message, sent_objs=None):
        super().__init__(message)
        self.sent_objs = sent_objs or []


class WatchNotFoundException(Exception):
    """
    Exception raised when the watch being notified for no longer exists.

    This is a non-recoverable error that should NOT be retried.
    The notification should be immediately marked as failed/dead-lettered.
    """
    pass


class NotificationConfigurationException(Exception):
    """
    Exception raised when notification configuration is invalid.

    This is a non-recoverable error that should NOT be retried.
    Examples: invalid notification URLs, missing required fields, etc.
    """
    pass
