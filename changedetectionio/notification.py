import os
import apprise

valid_tokens = {
    'base_url': '',
    'watch_url': '',
    'watch_uuid': '',
    'watch_title': '',
    'watch_tag': '',
    'diff_url': '',
    'preview_url': '',
    'current_snapshot': ''
}


def process_notification(n_object, datastore):
    apobj = apprise.Apprise()
    for url in n_object['notification_urls']:
        print (">> Process Notification: AppRise notifying {}".format(url.strip()))
        apobj.add(url.strip())

    # Get the notification body from datastore
    n_body = datastore.data['settings']['application']['notification_body']
    # Get the notification title from the datastore
    n_title = datastore.data['settings']['application']['notification_title']

    # Insert variables into the notification content
    notification_parameters = create_notification_parameters(n_object, datastore)
    raw_notification_text = [n_body, n_title]

    parameterised_notification_text = dict(
        [
            (i, n.replace(n, n.format(**notification_parameters)))
            for i, n in zip(['body', 'title'], raw_notification_text)
        ]
    )

    apobj.notify(
        body=parameterised_notification_text["body"],
        title=parameterised_notification_text["title"]
    )


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
    base_url = os.getenv('BASE_URL', '').strip('"')
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
        'base_url': base_url,
        'watch_url': watch_url,
        'watch_uuid': uuid,
        'watch_title': watch_title,
        'watch_tag': watch_tag,
        'diff_url': diff_url,
        'preview_url': preview_url,
        'current_snapshot': n_object['current_snapshot'] if 'current_snapshot' in n_object else ''
    })

    return tokens