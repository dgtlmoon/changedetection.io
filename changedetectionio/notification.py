import apprise
from apprise import NotifyFormat

valid_tokens = {
    'base_url': '',
    'watch_url': '',
    'watch_uuid': '',
    'watch_title': '',
    'watch_tag': '',
    'diff': '',
    'diff_full': '',
    'diff_url': '',
    'preview_url': '',
    'current_snapshot': ''
}

valid_notification_formats = {
    'Text': NotifyFormat.TEXT,
    'Markdown': NotifyFormat.MARKDOWN,
    'HTML': NotifyFormat.HTML,
}

default_notification_format = 'Text'
default_notification_body = '{watch_url} had a change.\n---\n{diff}\n---\n'
default_notification_title = 'ChangeDetection.io Notification - {watch_url}'

def process_notification(n_object, datastore):

    # Get the notification body from datastore
    n_body = n_object.get('notification_body', default_notification_body)
    n_title = n_object.get('notification_title', default_notification_title)
    n_format = valid_notification_formats.get(
        n_object['notification_format'],
        valid_notification_formats[default_notification_format],
    )


    # Insert variables into the notification content
    notification_parameters = create_notification_parameters(n_object, datastore)

    for n_k in notification_parameters:
        token = '{' + n_k + '}'
        val = notification_parameters[n_k]
        n_title = n_title.replace(token, val)
        n_body = n_body.replace(token, val)

    # https://github.com/caronc/apprise/wiki/Development_LogCapture
    # Anything higher than or equal to WARNING (which covers things like Connection errors)
    # raise it as an exception
    apobjs=[]
    for url in n_object['notification_urls']:

        apobj = apprise.Apprise(debug=True)
        url = url.strip()
        if len(url):
            print(">> Process Notification: AppRise notifying {}".format(url))
            with apprise.LogCapture(level=apprise.logging.DEBUG) as logs:
                # Re 323 - Limit discord length to their 2000 char limit total or it wont send.
                # Because different notifications may require different pre-processing, run each sequentially :(
                # 2000 bytes minus -
                #     200 bytes for the overhead of the _entire_ json payload, 200 bytes for {tts, wait, content} etc headers
                #     Length of URL - Incase they specify a longer custom avatar_url

                # So if no avatar_url is specified, add one so it can be correctly calculated into the total payload
                k = '?' if not '?' in url else '&'
                if not 'avatar_url' in url:
                    url += k + 'avatar_url=https://raw.githubusercontent.com/dgtlmoon/changedetection.io/master/changedetectionio/static/images/avatar-256x256.png'

                if url.startswith('tgram://'):
                    # real limit is 4096, but minus some for extra metadata
                    payload_max_size = 3600
                    body_limit = max(0, payload_max_size - len(n_title))
                    n_title = n_title[0:payload_max_size]
                    n_body = n_body[0:body_limit]

                elif url.startswith('discord://'):
                    # real limit is 2000, but minus some for extra metadata
                    payload_max_size = 1700
                    body_limit = max(0, payload_max_size - len(n_title))
                    n_title = n_title[0:payload_max_size]
                    n_body = n_body[0:body_limit]

                apobj.add(url)

                apobj.notify(
                    title=n_title,
                    body=n_body,
                    body_format=n_format)

                apobj.clear()

                # Incase it needs to exist in memory for a while after to process(?)
                apobjs.append(apobj)

                # Returns empty string if nothing found, multi-line string otherwise
                log_value = logs.getvalue()
                if log_value and 'WARNING' in log_value or 'ERROR' in log_value:
                    raise Exception(log_value)

# Notification title + body content parameters get created here.
def create_notification_parameters(n_object, datastore):
    from copy import deepcopy

    # in the case we send a test notification from the main settings, there is no UUID.
    uuid = n_object['uuid'] if 'uuid' in n_object else ''

    if uuid != '':
        watch_title = datastore.data['watching'][uuid]['title']
        watch_tag = datastore.data['watching'][uuid]['tag']
    else:
        watch_title = 'Change Detection'
        watch_tag = ''

    # Create URLs to customise the notification with
    base_url = datastore.data['settings']['application']['base_url']

    watch_url = n_object['watch_url']

    # Re #148 - Some people have just {base_url} in the body or title, but this may break some notification services
    #           like 'Join', so it's always best to atleast set something obvious so that they are not broken.
    if base_url == '':
        base_url = "<base-url-env-var-not-set>"

    diff_url = "{}/diff/{}".format(base_url, uuid)
    preview_url = "{}/preview/{}".format(base_url, uuid)

    # Not sure deepcopy is needed here, but why not
    tokens = deepcopy(valid_tokens)

    # Valid_tokens also used as a field validator
    tokens.update(
        {
            'base_url': base_url if base_url is not None else '',
            'watch_url': watch_url,
            'watch_uuid': uuid,
            'watch_title': watch_title if watch_title is not None else '',
            'watch_tag': watch_tag if watch_tag is not None else '',
            'diff_url': diff_url,
            'diff': n_object.get('diff', ''),  # Null default in the case we use a test
            'diff_full': n_object.get('diff_full', ''),  # Null default in the case we use a test
            'preview_url': preview_url,
            'current_snapshot': n_object['current_snapshot'] if 'current_snapshot' in n_object else ''
        })

    return tokens
