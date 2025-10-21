
import time
import apprise
from apprise import NotifyFormat
from loguru import logger
from urllib.parse import urlparse
from .apprise_plugin.assets import apprise_asset, APPRISE_AVATAR_URL
from .apprise_plugin.custom_handlers import SUPPORTED_HTTP_METHODS
from ..notification_service import NotificationContextData


def markup_text_links_to_html(body):
    """
    Convert plaintext to HTML with clickable links.
    Uses Jinja2's escape and Markup for XSS safety.
    """
    from linkify_it import LinkifyIt
    from markupsafe import Markup, escape

    linkify = LinkifyIt()

    # Match URLs in the ORIGINAL text (before escaping)
    matches = linkify.match(body)

    if not matches:
        # No URLs, just escape everything
        return Markup(escape(body))

    result = []
    last_index = 0

    # Process each URL match
    for match in matches:
        # Add escaped text before the URL
        if match.index > last_index:
            text_part = body[last_index:match.index]
            result.append(escape(text_part))

        # Add the link with escaped URL (both in href and display)
        url = match.url
        result.append(Markup(f'<a href="{escape(url)}">{escape(url)}</a>'))

        last_index = match.last_index

    # Add remaining escaped text
    if last_index < len(body):
        result.append(escape(body[last_index:]))

    # Join all parts
    return str(Markup(''.join(str(part) for part in result)))

def notification_format_align_with_apprise(n_format : str):
    """
    Correctly align changedetection's formats with apprise's formats
    Probably these are the same - but good to be sure.
    :param n_format:
    :return:
    """

    if n_format.lower().startswith('html'):
        # Apprise only knows 'html' not 'htmlcolor' etc, which shouldnt matter here
        n_format = NotifyFormat.HTML.value
    elif n_format.lower().startswith('markdown'):
        # probably the same but just to be safe
        n_format = NotifyFormat.MARKDOWN.value
    elif n_format.lower().startswith('text'):
        # probably the same but just to be safe
        n_format = NotifyFormat.TEXT.value
    else:
        n_format = NotifyFormat.TEXT.value

    return n_format

def process_notification(n_object: NotificationContextData, datastore):
    from changedetectionio.jinja2_custom import render as jinja_render
    from . import default_notification_format_for_watch, default_notification_format, valid_notification_formats
    # be sure its registered
    from .apprise_plugin.custom_handlers import apprise_http_custom_handler

    if not isinstance(n_object, NotificationContextData):
        raise TypeError(f"Expected NotificationContextData, got {type(n_object)}")

    now = time.time()
    if n_object.get('notification_timestamp'):
        logger.trace(f"Time since queued {now-n_object['notification_timestamp']:.3f}s")

    # Insert variables into the notification content
    notification_parameters = create_notification_parameters(n_object, datastore)

    n_format = valid_notification_formats.get(
        n_object.get('notification_format', default_notification_format),
        valid_notification_formats[default_notification_format],
    )

    # If we arrived with 'System default' then look it up
    if n_format == default_notification_format_for_watch and datastore.data['settings']['application'].get('notification_format') != default_notification_format_for_watch:
        # Initially text or whatever
        n_format = datastore.data['settings']['application'].get('notification_format', valid_notification_formats[default_notification_format]).lower()

    n_format = notification_format_align_with_apprise(n_format=n_format)

    logger.trace(f"Complete notification body including Jinja and placeholders calculated in  {time.time() - now:.2f}s")

    # https://github.com/caronc/apprise/wiki/Development_LogCapture
    # Anything higher than or equal to WARNING (which covers things like Connection errors)
    # raise it as an exception

    sent_objs = []

    if 'as_async' in n_object:
        apprise_asset.async_mode = n_object.get('as_async')

    apobj = apprise.Apprise(debug=True, asset=apprise_asset)

    if not n_object.get('notification_urls'):
        return None

    with apprise.LogCapture(level=apprise.logging.DEBUG) as logs:
        for url in n_object['notification_urls']:

            # Get the notification body from datastore
            n_body = jinja_render(template_str=n_object.get('notification_body', ''), **notification_parameters)

            if n_object.get('markup_text_to_html'):
                n_body = markup_text_links_to_html(body=n_body)

            if n_format == NotifyFormat.HTML.value:
                n_body = n_body.replace("\n", '<br>')

            n_title = jinja_render(template_str=n_object.get('notification_title', ''), **notification_parameters)

            url = url.strip()
            if url.startswith('#'):
                logger.trace(f"Skipping commented out notification URL - {url}")
                continue

            if not url:
                logger.warning(f"Process Notification: skipping empty notification URL.")
                continue

            logger.info(f">> Process Notification: AppRise notifying {url}")
            url = jinja_render(template_str=url, **notification_parameters)

            # Re 323 - Limit discord length to their 2000 char limit total or it wont send.
            # Because different notifications may require different pre-processing, run each sequentially :(
            # 2000 bytes minus -
            #     200 bytes for the overhead of the _entire_ json payload, 200 bytes for {tts, wait, content} etc headers
            #     Length of URL - Incase they specify a longer custom avatar_url

            # So if no avatar_url is specified, add one so it can be correctly calculated into the total payload
            parsed = urlparse(url)
            k = '?' if not parsed.query else '&'
            if not 'avatar_url' in url \
                    and not url.startswith('mail') \
                    and not url.startswith('post') \
                    and not url.startswith('get') \
                    and not url.startswith('delete') \
                    and not url.startswith('put'):
                url += k + f"avatar_url={APPRISE_AVATAR_URL}"

            if url.startswith('tgram://'):
                # Telegram only supports a limit subset of HTML, remove the '<br>' we place in.
                # re https://github.com/dgtlmoon/changedetection.io/issues/555
                # @todo re-use an existing library we have already imported to strip all non-allowed tags
                n_body = n_body.replace('<br>', '\n')
                n_body = n_body.replace('</br>', '\n')
                # real limit is 4096, but minus some for extra metadata
                payload_max_size = 3600
                body_limit = max(0, payload_max_size - len(n_title))
                n_title = n_title[0:payload_max_size]
                n_body = n_body[0:body_limit]

            elif url.startswith('discord://') or url.startswith('https://discordapp.com/api/webhooks') or url.startswith(
                    'https://discord.com/api'):
                # real limit is 2000, but minus some for extra metadata
                payload_max_size = 1700
                body_limit = max(0, payload_max_size - len(n_title))
                n_title = n_title[0:payload_max_size]
                n_body = n_body[0:body_limit]

            # Add format parameter to mailto URLs to ensure proper text/html handling
            # https://github.com/caronc/apprise/issues/633#issuecomment-1191449321
            # Note: Custom handlers (post://, get://, etc.) don't need this as we handle them
            # differently by passing an invalid body_format to prevent HTML conversion
            if not 'format=' in url and url.startswith(('mailto', 'mailtos')):
                parsed = urlparse(url)
                prefix = '?' if not parsed.query else '&'
                # Apprise format is already lowercase from notification_format_align_with_apprise()
                url = f"{url}{prefix}format={n_format}"

            apobj.add(url)

            sent_objs.append({'title': n_title,
                              'body': n_body,
                              'url': url,
                              'body_format': n_format})

        # Blast off the notifications tht are set in .add()
        # Check if we have any custom HTTP handlers (post://, get://, etc.)
        # These handlers created with @notify decorator don't handle format conversion properly
        # and will strip HTML if we pass a valid format. So we pass an invalid format string
        # to prevent Apprise from converting HTML->TEXT

        # Create list of custom handler protocols (both http and https versions)
        custom_handler_protocols = [f"{method}://" for method in SUPPORTED_HTTP_METHODS]
        custom_handler_protocols += [f"{method}s://" for method in SUPPORTED_HTTP_METHODS]

        has_custom_handler = any(
            url.startswith(tuple(custom_handler_protocols))
            for url in n_object['notification_urls']
        )

        # If we have custom handlers, use invalid format to prevent conversion
        # Otherwise use the proper format
        notify_format = 'raw-no-convert' if has_custom_handler else n_format

        apobj.notify(
            title=n_title,
            body=n_body,
            body_format=notify_format,
            # False is not an option for AppRise, must be type None
            attach=n_object.get('screenshot', None)
        )


        # Returns empty string if nothing found, multi-line string otherwise
        log_value = logs.getvalue()

        if log_value and ('WARNING' in log_value or 'ERROR' in log_value):
            logger.critical(log_value)
            raise Exception(log_value)

    # Return what was sent for better logging - after the for loop
    return sent_objs


# Notification title + body content parameters get created here.
# ( Where we prepare the tokens in the notification to be replaced with actual values )
def create_notification_parameters(n_object: NotificationContextData, datastore):
    if not isinstance(n_object, NotificationContextData):
        raise TypeError(f"Expected NotificationContextData, got {type(n_object)}")

    watch = datastore.data['watching'].get(n_object['uuid'])
    if watch:
        watch_title = datastore.data['watching'][n_object['uuid']].label
        tag_list = []
        tags = datastore.get_all_tags_for_watch(n_object['uuid'])
        if tags:
            for tag_uuid, tag in tags.items():
                tag_list.append(tag.get('title'))
        watch_tag = ', '.join(tag_list)
    else:
        watch_title = 'Change Detection'
        watch_tag = ''

    # Create URLs to customise the notification with
    # active_base_url - set in store.py data property
    base_url = datastore.data['settings']['application'].get('active_base_url')

    watch_url = n_object['watch_url']

    diff_url = "{}/diff/{}".format(base_url, n_object['uuid'])
    preview_url = "{}/preview/{}".format(base_url, n_object['uuid'])

    n_object.update(
        {
            'base_url': base_url,
            'diff_url': diff_url,
            'preview_url': preview_url,
            'watch_tag': watch_tag if watch_tag is not None else '',
            'watch_title': watch_title if watch_title is not None else '',
            'watch_url': watch_url,
            'watch_uuid': n_object['uuid'],
        })

    if watch:
        n_object.update(datastore.data['watching'].get(n_object['uuid']).extra_notification_token_values())

    return n_object
