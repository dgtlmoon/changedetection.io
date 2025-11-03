
import time
import re
import apprise
from apprise import NotifyFormat
from loguru import logger
from urllib.parse import urlparse
from .apprise_plugin.assets import apprise_asset, APPRISE_AVATAR_URL
from .email_helpers import as_monospaced_html_email
from ..diff import HTML_REMOVED_STYLE, REMOVED_PLACEMARKER_OPEN, REMOVED_PLACEMARKER_CLOSED, ADDED_PLACEMARKER_OPEN, HTML_ADDED_STYLE, \
    ADDED_PLACEMARKER_CLOSED, CHANGED_INTO_PLACEMARKER_OPEN, CHANGED_INTO_PLACEMARKER_CLOSED, CHANGED_PLACEMARKER_OPEN, \
    CHANGED_PLACEMARKER_CLOSED, HTML_CHANGED_STYLE, HTML_CHANGED_INTO_STYLE
import re

from ..notification_service import NotificationContextData, add_rendered_diff_to_notification_vars

newline_re = re.compile(r'\r\n|\r|\n')

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

    if n_format.startswith('html'):
        # Apprise only knows 'html' not 'htmlcolor' etc, which shouldnt matter here
        n_format = NotifyFormat.HTML.value
    elif n_format.startswith('markdown'):
        # probably the same but just to be safe
        n_format = NotifyFormat.MARKDOWN.value
    elif n_format.startswith('text'):
        # probably the same but just to be safe
        n_format = NotifyFormat.TEXT.value
    else:
        n_format = NotifyFormat.TEXT.value

    return n_format


def apply_html_color_to_body(n_body: str):
    # https://github.com/dgtlmoon/changedetection.io/issues/821#issuecomment-1241837050
    n_body = n_body.replace(REMOVED_PLACEMARKER_OPEN,
                            f'<span style="{HTML_REMOVED_STYLE}" role="deletion" aria-label="Removed text" title="Removed text">')
    n_body = n_body.replace(REMOVED_PLACEMARKER_CLOSED, f'</span>')
    n_body = n_body.replace(ADDED_PLACEMARKER_OPEN,
                            f'<span style="{HTML_ADDED_STYLE}" role="insertion" aria-label="Added text" title="Added text">')
    n_body = n_body.replace(ADDED_PLACEMARKER_CLOSED, f'</span>')
    # Handle changed/replaced lines (old → new)
    n_body = n_body.replace(CHANGED_PLACEMARKER_OPEN,
                            f'<span style="{HTML_CHANGED_STYLE}" role="note" aria-label="Changed text" title="Changed text">')
    n_body = n_body.replace(CHANGED_PLACEMARKER_CLOSED, f'</span>')
    n_body = n_body.replace(CHANGED_INTO_PLACEMARKER_OPEN,
                            f'<span style="{HTML_CHANGED_INTO_STYLE}" role="note" aria-label="Changed into" title="Changed into">')
    n_body = n_body.replace(CHANGED_INTO_PLACEMARKER_CLOSED, f'</span>')
    return n_body

def apply_discord_markdown_to_body(n_body):
    """
    Discord does not support <del> but it supports non-standard ~~strikethrough~~
    :param n_body:
    :return:
    """
    import re
    # Define the mapping between your placeholders and markdown markers
    replacements = [
        (REMOVED_PLACEMARKER_OPEN, '~~', REMOVED_PLACEMARKER_CLOSED, '~~'),
        (ADDED_PLACEMARKER_OPEN, '**', ADDED_PLACEMARKER_CLOSED, '**'),
        (CHANGED_PLACEMARKER_OPEN, '~~', CHANGED_PLACEMARKER_CLOSED, '~~'),
        (CHANGED_INTO_PLACEMARKER_OPEN, '**', CHANGED_INTO_PLACEMARKER_CLOSED, '**'),
    ]
    # So that the markdown gets added without any whitespace following it which would break it
    for open_tag, open_md, close_tag, close_md in replacements:
        # Regex: match opening tag, optional whitespace, capture the content, optional whitespace, then closing tag
        pattern = re.compile(
            re.escape(open_tag) + r'(\s*)(.*?)?(\s*)' + re.escape(close_tag),
            flags=re.DOTALL
        )
        n_body = pattern.sub(lambda m: f"{m.group(1)}{open_md}{m.group(2)}{close_md}{m.group(3)}", n_body)
    return n_body

def apply_standard_markdown_to_body(n_body):
    """
    Apprise does not support ~~strikethrough~~ but it will convert <del> to HTML strikethrough.
    :param n_body:
    :return:
    """
    import re
    # Define the mapping between your placeholders and markdown markers
    replacements = [
        (REMOVED_PLACEMARKER_OPEN, '<del>', REMOVED_PLACEMARKER_CLOSED, '</del>'),
        (ADDED_PLACEMARKER_OPEN, '**', ADDED_PLACEMARKER_CLOSED, '**'),
        (CHANGED_PLACEMARKER_OPEN, '<del>', CHANGED_PLACEMARKER_CLOSED, '</del>'),
        (CHANGED_INTO_PLACEMARKER_OPEN, '**', CHANGED_INTO_PLACEMARKER_CLOSED, '**'),
    ]

    # So that the markdown gets added without any whitespace following it which would break it
    for open_tag, open_md, close_tag, close_md in replacements:
        # Regex: match opening tag, optional whitespace, capture the content, optional whitespace, then closing tag
        pattern = re.compile(
            re.escape(open_tag) + r'(\s*)(.*?)?(\s*)' + re.escape(close_tag),
            flags=re.DOTALL
        )
        n_body = pattern.sub(lambda m: f"{m.group(1)}{open_md}{m.group(2)}{close_md}{m.group(3)}", n_body)
    return n_body


def replace_placemarkers_in_text(text, url, requested_output_format):
    """
    Replace diff placemarkers in text based on the URL service type and requested output format.
    Used for both notification title and body to ensure consistent placeholder replacement.

    :param text: The text to process
    :param url: The notification URL (to detect service type)
    :param requested_output_format: The output format (html, htmlcolor, markdown, text, etc.)
    :return: Processed text with placemarkers replaced
    """
    if not text:
        return text

    if url.startswith('tgram://'):
        # Telegram only supports a limited subset of HTML
        # Use strikethrough for removed content, bold for added content
        text = text.replace(REMOVED_PLACEMARKER_OPEN, '<s>')
        text = text.replace(REMOVED_PLACEMARKER_CLOSED, '</s>')
        text = text.replace(ADDED_PLACEMARKER_OPEN, '<b>')
        text = text.replace(ADDED_PLACEMARKER_CLOSED, '</b>')
        # Handle changed/replaced lines (old → new)
        text = text.replace(CHANGED_PLACEMARKER_OPEN, '<s>')
        text = text.replace(CHANGED_PLACEMARKER_CLOSED, '</s>')
        text = text.replace(CHANGED_INTO_PLACEMARKER_OPEN, '<b>')
        text = text.replace(CHANGED_INTO_PLACEMARKER_CLOSED, '</b>')
    elif (url.startswith('discord://') or url.startswith('https://discordapp.com/api/webhooks')
          or url.startswith('https://discord.com/api')) and requested_output_format == 'html':
        # Discord doesn't support HTML, use Discord markdown
        text = apply_discord_markdown_to_body(n_body=text)
    elif requested_output_format == 'htmlcolor':
        # https://github.com/dgtlmoon/changedetection.io/issues/821#issuecomment-1241837050
        text = text.replace(REMOVED_PLACEMARKER_OPEN, f'<span style="{HTML_REMOVED_STYLE}" role="deletion" aria-label="Removed text" title="Removed text">')
        text = text.replace(REMOVED_PLACEMARKER_CLOSED, f'</span>')
        text = text.replace(ADDED_PLACEMARKER_OPEN, f'<span style="{HTML_ADDED_STYLE}" role="insertion" aria-label="Added text" title="Added text">')
        text = text.replace(ADDED_PLACEMARKER_CLOSED, f'</span>')
        # Handle changed/replaced lines (old → new)
        text = text.replace(CHANGED_PLACEMARKER_OPEN, f'<span style="{HTML_CHANGED_STYLE}" role="note" aria-label="Changed text" title="Changed text">')
        text = text.replace(CHANGED_PLACEMARKER_CLOSED, f'</span>')
        text = text.replace(CHANGED_INTO_PLACEMARKER_OPEN, f'<span style="{HTML_CHANGED_INTO_STYLE}" role="note" aria-label="Changed into" title="Changed into">')
        text = text.replace(CHANGED_INTO_PLACEMARKER_CLOSED, f'</span>')
    elif requested_output_format == 'markdown':
        # Markdown to HTML - Apprise will convert this to HTML
        text = apply_standard_markdown_to_body(n_body=text)
    else:
        # plaintext, html, and default - use simple text markers
        text = text.replace(REMOVED_PLACEMARKER_OPEN, '(removed) ')
        text = text.replace(REMOVED_PLACEMARKER_CLOSED, '')
        text = text.replace(ADDED_PLACEMARKER_OPEN, '(added) ')
        text = text.replace(ADDED_PLACEMARKER_CLOSED, '')
        text = text.replace(CHANGED_PLACEMARKER_OPEN, f'(changed) ')
        text = text.replace(CHANGED_PLACEMARKER_CLOSED, f'')
        text = text.replace(CHANGED_INTO_PLACEMARKER_OPEN, f'(into) ')
        text = text.replace(CHANGED_INTO_PLACEMARKER_CLOSED, f'')

    return text

def apply_service_tweaks(url, n_body, n_title, requested_output_format):

    # Re 323 - Limit discord length to their 2000 char limit total or it wont send.
    # Because different notifications may require different pre-processing, run each sequentially :(
    # 2000 bytes minus -
    #     200 bytes for the overhead of the _entire_ json payload, 200 bytes for {tts, wait, content} etc headers
    #     Length of URL - Incase they specify a longer custom avatar_url

    if not n_body or not n_body.strip():
        return url, n_body, n_title

    # Normalize URL scheme to lowercase to prevent case-sensitivity issues
    # e.g., "Discord://webhook" -> "discord://webhook", "TGRAM://bot123" -> "tgram://bot123"
    scheme_separator_pos = url.find('://')
    if scheme_separator_pos > 0:
        url = url[:scheme_separator_pos].lower() + url[scheme_separator_pos:]

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

    # Replace placemarkers in title first (this was the missing piece causing the bug)
    # Titles are ALWAYS plain text across all notification services (Discord embeds, Slack attachments,
    # email Subject headers, etc.), so we always use 'text' format for title placemarker replacement
    # Looking over apprise library it seems that all plugins only expect plain-text.
    n_title = replace_placemarkers_in_text(n_title, url, 'text')

    if url.startswith('tgram://'):
        # Telegram only supports a limit subset of HTML, remove the '<br>' we place in.
        # re https://github.com/dgtlmoon/changedetection.io/issues/555
        # @todo re-use an existing library we have already imported to strip all non-allowed tags
        n_body = n_body.replace('<br>', '\n')
        n_body = n_body.replace('</br>', '\n')
        n_body = newline_re.sub('\n', n_body)

        # Replace placemarkers for body
        n_body = replace_placemarkers_in_text(n_body, url, requested_output_format)

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
        n_body = newline_re.sub('\n', n_body)

        # Don't replace placeholders or truncate here - let the custom Discord plugin handle it
        # The plugin will use embeds (6000 char limit across all embeds) if placeholders are present,
        # or plain content (2000 char limit) otherwise

        # Only do placeholder replacement if NOT using htmlcolor (which triggers embeds in custom plugin)
        if requested_output_format == 'html':
            # No diff placeholders, use Discord markdown for any other formatting
            # Use Discord markdown: strikethrough for removed, bold for added
            n_body = replace_placemarkers_in_text(n_body, url, requested_output_format)

            # Apply 2000 char limit for plain content
            payload_max_size = 1700
            body_limit = max(0, payload_max_size - len(n_title))
            n_title = n_title[0:payload_max_size]
            n_body = n_body[0:body_limit]
        # else: our custom Discord plugin will convert any placeholders left over into embeds with color bars

    # Is not discord/tgram and they want htmlcolor
    elif requested_output_format == 'htmlcolor':
        n_body = replace_placemarkers_in_text(n_body, url, requested_output_format)
        n_body = newline_re.sub('<br>\n', n_body)
    elif requested_output_format == 'html':
        n_body = replace_placemarkers_in_text(n_body, url, requested_output_format)
        n_body = newline_re.sub('<br>\n', n_body)
    elif requested_output_format == 'markdown':
        # Markdown to HTML - Apprise will convert this to HTML
        n_body = replace_placemarkers_in_text(n_body, url, requested_output_format)

    else: #plaintext etc default
        n_body = replace_placemarkers_in_text(n_body, url, requested_output_format)

    return url, n_body, n_title


def process_notification(n_object: NotificationContextData, datastore):
    from changedetectionio.jinja2_custom import render as jinja_render
    from . import USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH, default_notification_format, valid_notification_formats
    # be sure its registered
    from .apprise_plugin.custom_handlers import apprise_http_custom_handler
    # Register custom Discord plugin
    from .apprise_plugin.discord import NotifyDiscordCustom

    if not isinstance(n_object, NotificationContextData):
        raise TypeError(f"Expected NotificationContextData, got {type(n_object)}")

    now = time.time()
    if n_object.get('notification_timestamp'):
        logger.trace(f"Time since queued {now-n_object['notification_timestamp']:.3f}s")

    # Insert variables into the notification content
    notification_parameters = create_notification_parameters(n_object, datastore)

    requested_output_format = n_object.get('notification_format', default_notification_format)
    logger.debug(f"Requested notification output format: '{requested_output_format}'")

    # If we arrived with 'System default' then look it up
    if requested_output_format == USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH:
        # Initially text or whatever
        requested_output_format = datastore.data['settings']['application'].get('notification_format', default_notification_format)

    requested_output_format_original = requested_output_format

    # Now clean it up so it fits perfectly with apprise
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

    n_object.update(add_rendered_diff_to_notification_vars(
        notification_scan_text=n_object.get('notification_body', '')+n_object.get('notification_title', ''),
        current_snapshot=n_object.get('current_snapshot'),
        prev_snapshot=n_object.get('prev_snapshot'),
        # Should always be false for 'text' mode or its too hard to read
        # But otherwise, this could be some setting
        word_diff=False if requested_output_format_original == 'text' else True,
        )
    )

    with (apprise.LogCapture(level=apprise.logging.DEBUG) as logs):
        for url in n_object['notification_urls']:

            n_body = jinja_render(template_str=n_object.get('notification_body', ''), **notification_parameters)
            n_title = jinja_render(template_str=n_object.get('notification_title', ''), **notification_parameters)

            if n_object.get('markup_text_links_to_html_links'):
                n_body = markup_text_links_to_html(body=n_body)

            url = url.strip()
            if not url or url.startswith('#'):
                logger.debug(f"Skipping commented out or empty notification URL - '{url}'")
                continue

            logger.info(f">> Process Notification: AppRise start notifying '{url}'")
            url = jinja_render(template_str=url, **notification_parameters)

            # If it's a plaintext document, and they want HTML type email/alerts, so it needs to be escaped
            watch_mime_type = n_object.get('watch_mime_type')
            if watch_mime_type and 'text/' in watch_mime_type.lower() and not 'html' in watch_mime_type.lower():
                if 'html' in requested_output_format:
                    from markupsafe import escape
                    n_body = str(escape(n_body))

            if 'html' in requested_output_format:
                # Since the n_body is always some kind of text from the 'diff' engine, attempt to preserve whitespaces that get sent to the HTML output
                # But only where its more than 1 consecutive whitespace, otherwise "and this" becomes "and&nbsp;this" etc which is too much.
                n_body = n_body.replace('  ', '&nbsp;&nbsp;')

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
                    # Convert markdown to HTML ourselves since not all plugins do this
                    from apprise.conversion import markdown_to_html
                    # Make sure there are paragraph breaks around horizontal rules
                    n_body = n_body.replace('---', '\n\n---\n\n')
                    n_body = markdown_to_html(n_body)
                    url = f"{url}{prefix_add_to_url}format={NotifyFormat.HTML.value}"
                    requested_output_format = NotifyFormat.HTML.value
                    apprise_input_format = NotifyFormat.HTML.value  # Changed from MARKDOWN to HTML

            else:
                # ?format was IN the apprise URL, they are kind of on their own here, we will try our best
                if 'format=html' in url:
                    n_body = newline_re.sub('<br>\r\n', n_body)
                    # This will also prevent apprise from doing conversion
                    apprise_input_format = NotifyFormat.HTML.value
                    requested_output_format = NotifyFormat.HTML.value
                elif 'format=text' in url:
                    apprise_input_format = NotifyFormat.TEXT.value
                    requested_output_format = NotifyFormat.TEXT.value


            sent_objs.append({'title': n_title,
                              'body': n_body,
                              'url': url})
            apobj.add(url)

            # Since the output is always based on the plaintext of the 'diff' engine, wrap it nicely.
            # It should always be similar to the 'history' part of the UI.
            if url.startswith('mail') and 'html' in requested_output_format:
                if not '<pre' in n_body and not '<body' in n_body: # No custom HTML-ish body was setup already
                    n_body = as_monospaced_html_email(content=n_body, title=n_title)

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
