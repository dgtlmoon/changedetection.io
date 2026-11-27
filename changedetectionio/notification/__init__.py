from changedetectionio.model import USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH

# How a group's own notification settings relate to the notifications of its watches.
# 'off' is what a new group gets: its notification settings can be filled in ahead of time, or switched off for a
# while, without anything being sent with them.
GROUP_NOTIFICATION_MODE_OFF = 'off'            # Not used
GROUP_NOTIFICATION_MODE_FALLBACK = 'fallback'  # One step in the watch > group > system lookup
GROUP_NOTIFICATION_MODE_ADD = 'add'            # Sent on its own, as well as the watch's
GROUP_NOTIFICATION_MODE_REPLACE = 'replace'    # Sent on its own, instead of the watch's


def group_notification_mode_for_older_data(group):
    """The mode of a group that was saved before 'off' existed, so that it goes on notifying exactly as it did.

    Back then every group was part of the watch > group > system lookup ('fallback'), unless it was set to 'add'
    or 'replace'. A group with notification URLs keeps that. One without any could not send anything of its own,
    all it did was hand its title, body or format to the notifications of its watches - that one becomes 'off'.

    Used by the datastore update that brought 'off' in, and for groups restored from an older backup.
    """
    mode = group.get('notification_group_mode')
    if mode in (GROUP_NOTIFICATION_MODE_ADD, GROUP_NOTIFICATION_MODE_REPLACE):
        return mode
    return GROUP_NOTIFICATION_MODE_FALLBACK if group.get('notification_urls') else GROUP_NOTIFICATION_MODE_OFF


default_notification_format = 'htmlcolor'
default_notification_body = '{{watch_url}} had a change.\n---\n{{diff}}\n---\n'
default_notification_title = 'ChangeDetection.io Notification - {{watch_url}}'

# The values (markdown etc) are from apprise NotifyFormat,
# But to avoid importing the whole heavy module just use the same strings here.
valid_notification_formats = {
    'text': 'Plain Text',
    'html': 'HTML',
    'htmlcolor': 'HTML Color',
    'markdown': 'Markdown to HTML',
    # Used only for editing a watch (not for global)
    USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH: USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH
}
