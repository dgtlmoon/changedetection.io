"""
Huey Message Unpacker - Centralized pickle unpacking for Huey messages.

Eliminates duplicate code and centralizes error handling for unpacking
Huey's pickled messages from queue and schedule storage.
"""

import pickle
from typing import Optional, Tuple, Dict
from datetime import datetime
from loguru import logger


class HueyMessageUnpacker:
    """
    Utility class for unpacking Huey messages safely and consistently.

    Handles:
    - Pickle deserialization errors
    - Revoked task filtering
    - Notification data extraction
    - Scheduled task ETA extraction
    """

    @staticmethod
    def unpack_queued_notification(pickled_bytes, huey) -> Optional[Tuple[str, Dict]]:
        """
        Unpack a queued (immediate execution) Huey message.

        Args:
            pickled_bytes: Pickled Huey message from queue
            huey: Huey instance for revocation checks

        Returns:
            (task_id, notification_data) or None if revoked/invalid
        """
        try:
            message = pickle.loads(pickled_bytes)

            # Extract task ID
            task_id = message.id if hasattr(message, 'id') else None

            # Skip revoked tasks
            if task_id and huey.is_revoked(task_id):
                logger.debug(f"Skipping revoked task {task_id}")
                return None

            # Extract notification data from message args
            if hasattr(message, 'args') and message.args:
                notification_data = message.args[0]
                return (task_id, notification_data)
            else:
                logger.debug(f"Message {task_id} has no args")
                return None

        except Exception as e:
            logger.debug(f"Error unpacking queued message: {e}")
            return None

    @staticmethod
    def unpack_scheduled_notification(pickled_bytes, huey) -> Optional[Tuple[str, Dict, Optional[datetime]]]:
        """
        Unpack a scheduled (retry/delayed) Huey message.

        Args:
            pickled_bytes: Pickled Huey message from schedule
            huey: Huey instance for revocation checks

        Returns:
            (task_id, notification_data, eta) or None if revoked/invalid
            eta is a datetime object representing when the task should execute
        """
        try:
            message = pickle.loads(pickled_bytes)

            # Extract task ID
            task_id = message.id if hasattr(message, 'id') else None

            # Skip revoked tasks
            if task_id and huey.is_revoked(task_id):
                logger.debug(f"Skipping revoked scheduled task {task_id}")
                return None

            # Extract notification data from message args
            if not (hasattr(message, 'args') and message.args):
                logger.debug(f"Scheduled message {task_id} has no args")
                return None

            notification_data = message.args[0]

            # Extract ETA (when task should execute)
            eta = message.eta if hasattr(message, 'eta') else None

            return (task_id, notification_data, eta)

        except Exception as e:
            logger.debug(f"Error unpacking scheduled message: {e}")
            return None

    @staticmethod
    def calculate_retry_timing(eta: Optional[datetime]) -> Tuple[int, str]:
        """
        Calculate retry timing information from ETA.

        Args:
            eta: datetime when task should execute (may be naive or timezone-aware)

        Returns:
            (retry_in_seconds, eta_formatted) - seconds until retry and formatted time
        """
        if not eta:
            return (0, 'Unknown')

        try:
            # Handle both naive and timezone-aware datetimes
            if eta.tzinfo is not None:
                # Timezone-aware
                now = datetime.now(eta.tzinfo)
                # Convert to local timezone for display
                local_tz = datetime.now().astimezone().tzinfo
                eta_local = eta.astimezone(local_tz)
                eta_formatted = eta_local.strftime('%Y-%m-%d %H:%M:%S %Z')
            else:
                # Naive datetime
                now = datetime.now()
                eta_formatted = eta.strftime('%Y-%m-%d %H:%M:%S')

            retry_in_seconds = int((eta - now).total_seconds())
            return (retry_in_seconds, eta_formatted)

        except Exception as e:
            logger.debug(f"Error calculating retry timing: {e}")
            return (0, 'Unknown')

    @staticmethod
    def extract_task_id_from_scheduled(pickled_bytes) -> Optional[str]:
        """
        Quick extraction of just the task ID from a scheduled message.

        Used for checking if a task is still scheduled without full unpacking.

        Args:
            pickled_bytes: Pickled Huey message

        Returns:
            task_id string or None
        """
        try:
            message = pickle.loads(pickled_bytes)
            return message.id if hasattr(message, 'id') else None
        except Exception as e:
            logger.debug(f"Error extracting task ID: {e}")
            return None
