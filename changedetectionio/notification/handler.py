
import time
import apprise
from apprise import NotifyFormat
from loguru import logger
from urllib.parse import urlparse
from .apprise_plugin.assets import apprise_asset, APPRISE_AVATAR_URL
from .apprise_plugin.custom_handlers import SUPPORTED_HTTP_METHODS
from ..diff import HTML_REMOVED_STYLE, REMOVED_PLACEMARKER_OPEN, REMOVED_PLACEMARKER_CLOSED, ADDED_PLACEMARKER_OPEN, HTML_ADDED_STYLE, \
    ADDED_PLACEMARKER_CLOSED, CHANGED_INTO_PLACEMARKER_OPEN, CHANGED_INTO_PLACEMARKER_CLOSED, CHANGED_PLACEMARKER_OPEN, \
    CHANGED_PLACEMARKER_CLOSED, HTML_CHANGED_STYLE
from ..notification_service import NotificationContextData

CUSTOM_LINEBREAK_PLACEHOLDER='$$BR$$'

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
    These set the expected OUTPUT format type
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


def apply_service_tweaks(url, n_body, n_title, requested_output_format):

    # Re 323 - Limit discord length to their 2000 char limit total or it wont send.
    # Because different notifications may require different pre-processing, run each sequentially :(
    # 2000 bytes minus -
    #     200 bytes for the overhead of the _entire_ json payload, 200 bytes for {tts, wait, content} etc headers
    #     Length of URL - Incase they specify a longer custom avatar_url

    if not n_body or not n_body.strip():
        return url, n_body, n_title

    # So if no avatar_url is specified, add one so it can be correctly calculated into the total payload
    parsed = urlparse(url)
    k = '?' if not parsed.query else '&'
    if url and not 'avatar_url' in url \
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

        # Use strikethrough for removed content, bold for added content
        n_body = n_body.replace(REMOVED_PLACEMARKER_OPEN, '<s>')
        n_body = n_body.replace(REMOVED_PLACEMARKER_CLOSED, '</s>')
        n_body = n_body.replace(ADDED_PLACEMARKER_OPEN, '<b>')
        n_body = n_body.replace(ADDED_PLACEMARKER_CLOSED, '</b>')
        # Handle changed/replaced lines (old → new)
        n_body = n_body.replace(CHANGED_PLACEMARKER_OPEN, '<s>')
        n_body = n_body.replace(CHANGED_PLACEMARKER_CLOSED, '</s>')
        n_body = n_body.replace(CHANGED_INTO_PLACEMARKER_OPEN, '<b>')
        n_body = n_body.replace(CHANGED_INTO_PLACEMARKER_CLOSED, '</b>')

        # real limit is 4096, but minus some for extra metadata
        payload_max_size = 3600
        body_limit = max(0, payload_max_size - len(n_title))
        n_title = n_title[0:payload_max_size]
        n_body = n_body[0:body_limit]

    elif (url.startswith('discord://') or url.startswith('https://discordapp.com/api/webhooks')
          or url.startswith('https://discord.com/api'))\
            and 'html' in requested_output_format:
        # Discord doesn't support HTML, replace <br> with newlines
        n_body = n_body.strip().replace('<br>', '\n')
        n_body = n_body.replace('</br>', '\n')

        # Don't replace placeholders or truncate here - let the custom Discord plugin handle it
        # The plugin will use embeds (6000 char limit across all embeds) if placeholders are present,
        # or plain content (2000 char limit) otherwise

        # Only do placeholder replacement if NOT using htmlcolor (which triggers embeds in custom plugin)
        if requested_output_format == 'html':
            # No diff placeholders, use Discord markdown for any other formatting
            # Use Discord markdown: strikethrough for removed, bold for added
            n_body = n_body.replace(REMOVED_PLACEMARKER_OPEN, '~~')
            n_body = n_body.replace(REMOVED_PLACEMARKER_CLOSED, '~~')
            n_body = n_body.replace(ADDED_PLACEMARKER_OPEN, '**')
            n_body = n_body.replace(ADDED_PLACEMARKER_CLOSED, '**')
            # Handle changed/replaced lines (old → new)
            n_body = n_body.replace(CHANGED_PLACEMARKER_OPEN, '~~')
            n_body = n_body.replace(CHANGED_PLACEMARKER_CLOSED, '~~')
            n_body = n_body.replace(CHANGED_INTO_PLACEMARKER_OPEN, '**')
            n_body = n_body.replace(CHANGED_INTO_PLACEMARKER_CLOSED, '**')

            # Apply 2000 char limit for plain content
            payload_max_size = 1700
            body_limit = max(0, payload_max_size - len(n_title))
            n_title = n_title[0:payload_max_size]
            n_body = n_body[0:body_limit]
        # else: our custom Discord plugin will convert any placeholders left over into embeds with color bars

    # Is not discord/tgram and they want htmlcolor
    elif requested_output_format == 'htmlcolor':
        # https://github.com/dgtlmoon/changedetection.io/issues/821#issuecomment-1241837050
        n_body = n_body.replace(REMOVED_PLACEMARKER_OPEN, f'<span style="{HTML_REMOVED_STYLE}" role="deletion" aria-label="Removed text" title="Removed text">')
        n_body = n_body.replace(REMOVED_PLACEMARKER_CLOSED, f'</span>')
        n_body = n_body.replace(ADDED_PLACEMARKER_OPEN, f'<span style="{HTML_ADDED_STYLE}" role="insertion" aria-label="Added text" title="Added text">')
        n_body = n_body.replace(ADDED_PLACEMARKER_CLOSED, f'</span>')
        # Handle changed/replaced lines (old → new)
        n_body = n_body.replace(CHANGED_PLACEMARKER_OPEN, f'<span style="{HTML_CHANGED_STYLE}" role="note" aria-label="Changed text" title="Changed text">')
        n_body = n_body.replace(CHANGED_PLACEMARKER_CLOSED, f'</span>')
        n_body = n_body.replace(CHANGED_INTO_PLACEMARKER_OPEN, f'<span style="{HTML_CHANGED_STYLE}" role="note" aria-label="Changed into" title="Changed into">')
        n_body = n_body.replace(CHANGED_INTO_PLACEMARKER_CLOSED, f'</span>')
        n_body = n_body.replace('\n', f'{CUSTOM_LINEBREAK_PLACEHOLDER}\n')
    elif requested_output_format == 'html':
        n_body = n_body.replace(REMOVED_PLACEMARKER_OPEN, '(removed) ')
        n_body = n_body.replace(REMOVED_PLACEMARKER_CLOSED, '')
        n_body = n_body.replace(ADDED_PLACEMARKER_OPEN, '(added) ')
        n_body = n_body.replace(ADDED_PLACEMARKER_CLOSED, '')
        n_body = n_body.replace(CHANGED_PLACEMARKER_OPEN, f'(changed) ')
        n_body = n_body.replace(CHANGED_PLACEMARKER_CLOSED, f'')
        n_body = n_body.replace(CHANGED_INTO_PLACEMARKER_OPEN, f'(into) ')
        n_body = n_body.replace(CHANGED_INTO_PLACEMARKER_CLOSED, f'')
        n_body = n_body.replace('\n', f'{CUSTOM_LINEBREAK_PLACEHOLDER}\n')

    else: #plaintext etc default
        n_body = n_body.replace(REMOVED_PLACEMARKER_OPEN, '(removed) ')
        n_body = n_body.replace(REMOVED_PLACEMARKER_CLOSED, '')
        n_body = n_body.replace(ADDED_PLACEMARKER_OPEN, '(added) ')
        n_body = n_body.replace(ADDED_PLACEMARKER_CLOSED, '')
        n_body = n_body.replace(CHANGED_PLACEMARKER_OPEN, f'(changed) ')
        n_body = n_body.replace(CHANGED_PLACEMARKER_CLOSED, f'')
        n_body = n_body.replace(CHANGED_INTO_PLACEMARKER_OPEN, f'(into) ')
        n_body = n_body.replace(CHANGED_INTO_PLACEMARKER_CLOSED, f'')

    return url, n_body, n_title


def process_notification(n_object: NotificationContextData, datastore):
    from changedetectionio.jinja2_custom import render as jinja_render
    from . import default_notification_format_for_watch, default_notification_format, valid_notification_formats
    # be sure its registered
    from .apprise_plugin.custom_handlers import apprise_http_custom_handler
    # Register custom Discord plugin
    from .apprise_plugin.discord import NotifyDiscordCustom

    # Create list of custom handler protocols (both http and https versions)
    custom_handler_protocols = [f"{method}://" for method in SUPPORTED_HTTP_METHODS]
    custom_handler_protocols += [f"{method}s://" for method in SUPPORTED_HTTP_METHODS]

    has_custom_handler = any(
        url.startswith(tuple(custom_handler_protocols))
        for url in n_object['notification_urls']
    )

    if not isinstance(n_object, NotificationContextData):
        raise TypeError(f"Expected NotificationContextData, got {type(n_object)}")

    now = time.time()
    if n_object.get('notification_timestamp'):
        logger.trace(f"Time since queued {now-n_object['notification_timestamp']:.3f}s")

    # Insert variables into the notification content
    notification_parameters = create_notification_parameters(n_object, datastore)

    requested_output_format = valid_notification_formats.get(
        n_object.get('notification_format', default_notification_format),
        valid_notification_formats[default_notification_format],
    )

    # If we arrived with 'System default' then look it up
    if requested_output_format == default_notification_format_for_watch and datastore.data['settings']['application'].get('notification_format') != default_notification_format_for_watch:
        # Initially text or whatever
        requested_output_format = datastore.data['settings']['application'].get('notification_format', valid_notification_formats[default_notification_format]).lower()

    requested_output_format_original = requested_output_format

    requested_output_format = notification_format_align_with_apprise(n_format=requested_output_format)

    logger.trace(f"Complete notification body including Jinja and placeholders calculated in  {time.time() - now:.2f}s")

    # https://github.com/caronc/apprise/wiki/Development_LogCapture
    # Anything higher than or equal to WARNING (which covers things like Connection errors)
    # raise it as an exception

    sent_objs = []

    if 'as_async' in n_object:
        apprise_asset.async_mode = n_object.get('as_async')

    apobj = apprise.Apprise(debug=True, asset=apprise_asset)

    # Override Apprise's built-in Discord plugin with our custom one
    # This allows us to use colored embeds for diff content
    # First remove the built-in discord plugin, then add our custom one
    apprise.plugins.N_MGR.remove('discord')
    apprise.plugins.N_MGR.add(NotifyDiscordCustom, schemas='discord')

    if not n_object.get('notification_urls'):
        return None

    with (apprise.LogCapture(level=apprise.logging.DEBUG) as logs):
        for url in n_object['notification_urls']:

            # Get the notification body from datastore
            n_body = jinja_render(template_str=n_object.get('notification_body', ''), **notification_parameters)

            if n_object.get('markup_text_links_to_html_links'):
                n_body = markup_text_links_to_html(body=n_body)


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

            (url, n_body, n_title) = apply_service_tweaks(url=url, n_body=n_body, n_title=n_title, requested_output_format=requested_output_format_original)

            apprise_input_format = "NO-THANKS-WE-WILL-MANAGE-ALL-OF-THIS"

            if not 'format=' in url:
                parsed_url = urlparse(url)
                prefix_add_to_url = '?' if not parsed_url.query else '&'

                # THIS IS THE TRICK HOW TO DISABLE APPRISE DOING WEIRD AUTO-CONVERSION WITH BREAKING BR TAGS ETC
                if 'html' in requested_output_format:
                    url = f"{url}{prefix_add_to_url}format={NotifyFormat.HTML.value}"
                    apprise_input_format = NotifyFormat.HTML.value
                elif 'text' in requested_output_format:
                    url = f"{url}{prefix_add_to_url}format={NotifyFormat.TEXT.value}"
                    apprise_input_format = NotifyFormat.TEXT.value

                elif requested_output_format == NotifyFormat.MARKDOWN.value:
                    # This actually means we request "Markdown to HTML", we want HTML output
                    url = f"{url}{prefix_add_to_url}format={NotifyFormat.HTML.value}"
                    requested_output_format = NotifyFormat.HTML.value
                    apprise_input_format = NotifyFormat.MARKDOWN.value

                # If it's a plaintext document, and they want HTML type email/alerts, so it needs to be escaped
                watch_mime_type = n_object.get('watch_mime_type', '').lower()
                if watch_mime_type and 'text/' in watch_mime_type and not 'html' in watch_mime_type:
                    if 'html' in requested_output_format:
                        from markupsafe import escape
                        n_body = str(escape(n_body))

                # Could have arrived at any stage, so we dont end up running .escape on it
                if 'html' in requested_output_format:
                    n_body = n_body.replace(CUSTOM_LINEBREAK_PLACEHOLDER, '<br>')
                else:
                    # Just incase
                    n_body = n_body.replace(CUSTOM_LINEBREAK_PLACEHOLDER, '')


            apobj.add(url)

            sent_objs.append({'title': n_title,
                              'body': n_body,
                              'url': url})

        apobj.notify(
            title=n_title,
            body=n_body,
            # `body_format` Tell apprise what format the INPUT is in, specify a wrong/bad type and it will force skip conversion in apprise
            # &format= in URL Tell apprise what format the OUTPUT should be in (it can convert between)
            body_format=apprise_input_format,
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
