from changedetectionio.model import default_notification_format_for_watch

default_notification_format = 'HTML Color'
default_notification_body = '{{watch_url}} had a change.\n---\n{{diff}}\n---\n'
default_notification_title = 'ChangeDetection.io Notification - {{watch_url}}'

# The values (markdown etc) are from apprise NotifyFormat,
# But to avoid importing the whole heavy module just use the same strings here.
valid_notification_formats = {
    'Plain Text': 'text',
    'HTML': 'html',
    'HTML Color': 'htmlcolor',
    'Markdown to HTML': 'markdown',
    # Used only for editing a watch (not for global)
    default_notification_format_for_watch: default_notification_format_for_watch
}

