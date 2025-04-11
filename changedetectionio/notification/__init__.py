from changedetectionio.model import default_notification_format_for_watch

ult_notification_format_for_watch = 'System default'
default_notification_format = 'HTML Color'
default_notification_body = '{{watch_url}} had a change.\n---\n{{diff}}\n---\n'
default_notification_title = 'ChangeDetection.io Notification - {{watch_url}}'

# The values (markdown etc) are from apprise NotifyFormat,
# But to avoid importing the whole heavy module just use the same strings here.
valid_notification_formats = {
    'Text': 'text',
    'Markdown': 'markdown',
    'HTML': 'html',
    'HTML Color': 'htmlcolor',
    # Used only for editing a watch (not for global)
    default_notification_format_for_watch: default_notification_format_for_watch
}


valid_tokens = {
    'base_url': '',
    'current_snapshot': '',
    'diff': '',
    'diff_added': '',
    'diff_full': '',
    'diff_patch': '',
    'diff_removed': '',
    'diff_url': '',
    'preview_url': '',
    'triggered_text': '',
    'watch_tag': '',
    'watch_title': '',
    'watch_url': '',
    'watch_uuid': '',
}
