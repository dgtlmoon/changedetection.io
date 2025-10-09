#!/usr/bin/env python3

"""
Notification Service Module
Extracted from update_worker.py to provide standalone notification functionality
for both sync and async workers
"""

import time
from loguru import logger


class NotificationService:
    """
    Standalone notification service that handles all notification functionality
    previously embedded in the update_worker class
    """
    
    def __init__(self, datastore, notification_q):
        self.datastore = datastore
        self.notification_q = notification_q
    
    def queue_notification_for_watch(self, n_object, watch):
        """
        Queue a notification for a watch. Diff rendering and template variables will be
        handled by process_notification() to ensure consistency with test notifications.
        """
        now = time.time()

        # Add basic metadata for the notification
        n_object.update({
            'notification_timestamp': now,
            'uuid': watch.get('uuid') if watch else None,
            'watch_url': watch.get('url') if watch else None,
        })

        if watch:
            n_object.update(watch.extra_notification_token_values())

        logger.debug("Queued notification for sending")
        self.notification_q.put(n_object)

    def _check_cascading_vars(self, var_name, watch):
        """
        Check notification variables in cascading priority:
        Individual watch settings > Tag settings > Global settings
        """
        from changedetectionio.notification import (
            default_notification_format_for_watch,
            default_notification_body,
            default_notification_title
        )

        # Would be better if this was some kind of Object where Watch can reference the parent datastore etc
        v = watch.get(var_name)
        if v and not watch.get('notification_muted'):
            if var_name == 'notification_format' and v == default_notification_format_for_watch:
                return self.datastore.data['settings']['application'].get('notification_format')

            return v

        tags = self.datastore.get_all_tags_for_watch(uuid=watch.get('uuid'))
        if tags:
            for tag_uuid, tag in tags.items():
                v = tag.get(var_name)
                if v and not tag.get('notification_muted'):
                    return v

        if self.datastore.data['settings']['application'].get(var_name):
            return self.datastore.data['settings']['application'].get(var_name)

        # Otherwise could be defaults
        if var_name == 'notification_format':
            return default_notification_format_for_watch
        if var_name == 'notification_body':
            return default_notification_body
        if var_name == 'notification_title':
            return default_notification_title

        return None

    def send_content_changed_notification(self, watch_uuid):
        """
        Send notification when content changes are detected
        """
        n_object = {}
        watch = self.datastore.data['watching'].get(watch_uuid)
        if not watch:
            return

        watch_history = watch.history
        dates = list(watch_history.keys())
        # Theoretically it's possible that this could be just 1 long,
        # - In the case that the timestamp key was not unique
        if len(dates) == 1:
            raise ValueError(
                "History index had 2 or more, but only 1 date loaded, timestamps were not unique? maybe two of the same timestamps got written, needs more delay?"
            )

        # Should be a better parent getter in the model object

        # Prefer - Individual watch settings > Tag settings >  Global settings (in that order)
        n_object['notification_urls'] = self._check_cascading_vars('notification_urls', watch)
        n_object['notification_title'] = self._check_cascading_vars('notification_title', watch)
        n_object['notification_body'] = self._check_cascading_vars('notification_body', watch)
        n_object['notification_format'] = self._check_cascading_vars('notification_format', watch)

        # (Individual watch) Only prepare to notify if the rules above matched
        queued = False
        if n_object and n_object.get('notification_urls'):
            queued = True

            count = watch.get('notification_alert_count', 0) + 1
            self.datastore.update_watch(uuid=watch_uuid, update_obj={'notification_alert_count': count})

            self.queue_notification_for_watch(n_object=n_object, watch=watch)

        return queued

    def send_filter_failure_notification(self, watch_uuid):
        """
        Send notification when CSS/XPath filters fail consecutively
        """
        threshold = self.datastore.data['settings']['application'].get('filter_failure_notification_threshold_attempts')
        watch = self.datastore.data['watching'].get(watch_uuid)
        if not watch:
            return

        n_object = {'notification_title': 'Changedetection.io - Alert - CSS/xPath filter was not present in the page',
                    'notification_body': "Your configured CSS/xPath filters of '{}' for {{{{watch_url}}}} did not appear on the page after {} attempts, did the page change layout?\n\nLink: {{{{base_url}}}}/edit/{{{{watch_uuid}}}}\n\nThanks - Your omniscient changedetection.io installation :)\n".format(
                        ", ".join(watch['include_filters']),
                        threshold),
                    'notification_format': 'text'}

        if len(watch['notification_urls']):
            n_object['notification_urls'] = watch['notification_urls']

        elif len(self.datastore.data['settings']['application']['notification_urls']):
            n_object['notification_urls'] = self.datastore.data['settings']['application']['notification_urls']

        # Only prepare to notify if the rules above matched
        if 'notification_urls' in n_object:
            n_object.update({
                'watch_url': watch['url'],
                'uuid': watch_uuid,
                'screenshot': None
            })
            self.notification_q.put(n_object)
            logger.debug(f"Sent filter not found notification for {watch_uuid}")
        else:
            logger.debug(f"NOT sending filter not found notification for {watch_uuid} - no notification URLs")

    def send_step_failure_notification(self, watch_uuid, step_n):
        """
        Send notification when browser steps fail consecutively
        """
        watch = self.datastore.data['watching'].get(watch_uuid, False)
        if not watch:
            return
        threshold = self.datastore.data['settings']['application'].get('filter_failure_notification_threshold_attempts')
        n_object = {'notification_title': "Changedetection.io - Alert - Browser step at position {} could not be run".format(step_n+1),
                    'notification_body': "Your configured browser step at position {} for {{{{watch_url}}}} "
                                         "did not appear on the page after {} attempts, did the page change layout? "
                                         "Does it need a delay added?\n\nLink: {{{{base_url}}}}/edit/{{{{watch_uuid}}}}\n\n"
                                         "Thanks - Your omniscient changedetection.io installation :)\n".format(step_n+1, threshold),
                    'notification_format': 'text'}

        if len(watch['notification_urls']):
            n_object['notification_urls'] = watch['notification_urls']

        elif len(self.datastore.data['settings']['application']['notification_urls']):
            n_object['notification_urls'] = self.datastore.data['settings']['application']['notification_urls']

        # Only prepare to notify if the rules above matched
        if 'notification_urls' in n_object:
            n_object.update({
                'watch_url': watch['url'],
                'uuid': watch_uuid
            })
            self.notification_q.put(n_object)
            logger.error(f"Sent step not found notification for {watch_uuid}")


# Convenience functions for creating notification service instances
def create_notification_service(datastore, notification_q):
    """
    Factory function to create a NotificationService instance
    """
    return NotificationService(datastore, notification_q)