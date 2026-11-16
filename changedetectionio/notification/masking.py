"""Notification URLs carry their own credentials (mailto://user:password@..., webhook tokens), these
are the forms of them that are fit for a log line, the notification log or an assistant."""


def mask_notification_url(url):
    """An Apprise URL with its secrets hidden"""
    try:
        import apprise
        # Registers changedetection.io's own get:// post:// ... handlers so their URLs can be read too
        import changedetectionio.notification.apprise_plugin.custom_handlers  # noqa: F401
        instance = apprise.Apprise.instantiate(url)
        if instance:
            masked = instance.url(privacy=True)
            if masked.rstrip('/').endswith(':'):
                # changedetection.io's own get:// post:// ... handlers give back the scheme alone. Say
                # where it goes at least, the path and query can be the secret (a webhook) so not those.
                from urllib.parse import urlsplit
                host = urlsplit(url).hostname
                if host:
                    return f"{masked.rstrip('/')}//{host}/****"
            return masked
    except Exception:
        pass
    scheme = url.split('://', 1)[0] if '://' in url else ''
    return f"{scheme}://****" if scheme else '****'


def mask_sent_notifications(sent_objs):
    """What process_notification() returns, as a copy with every notification URL in it masked"""
    masked = []
    for sent in sent_objs or []:
        sent = dict(sent)
        if sent.get('url'):
            sent['url'] = mask_notification_url(sent['url'])
        context = sent.get('original_context')
        if isinstance(context, dict) and context.get('notification_urls'):
            context = dict(context)
            context['notification_urls'] = [mask_notification_url(u) for u in context['notification_urls']]
            sent['original_context'] = context
        masked.append(sent)
    return masked
