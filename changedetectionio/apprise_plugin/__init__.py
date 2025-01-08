# include the decorator
from apprise.decorators import notify
from loguru import logger


@notify(on="delete")
@notify(on="deletes")
@notify(on="get")
@notify(on="gets")
@notify(on="post")
@notify(on="posts")
@notify(on="put")
@notify(on="puts")
def apprise_custom_api_call_wrapper(body, title, notify_type, *args, **kwargs):
    import requests
    import json
    import re

    from urllib.parse import unquote_plus
    from apprise.utils.parse import parse_url as apprise_parse_url

    url = kwargs['meta'].get('url')
    schema = kwargs['meta'].get('schema').lower().strip()

    # Choose POST, GET etc from requests
    requests_method = getattr(requests, re.sub(rf's$', '', schema))

    if schema.lower().endswith('s'):
        url = re.sub(rf'^{schema}', 'https', url)
    else:
        url = re.sub(rf'^{schema}', 'http', url)

    headers = {}
    params = {}
    auth = None
    has_error = False


    # Convert /foobar?+some-header=hello to proper header dictionary
    results = apprise_parse_url(url)
    if results:
        # Add our headers that the user can potentially over-ride if they wish
        # to to our returned result set and tidy entries by unquoting them
        headers = {unquote_plus(x): unquote_plus(y)
                   for x, y in results['qsd+'].items()}

        # https://github.com/caronc/apprise/wiki/Notify_Custom_JSON#get-parameter-manipulation
        # In Apprise, it relies on prefixing each request arg with "-", because it uses say &method=update as a flag for apprise
        # but here we are making straight requests, so we need todo convert this against apprise's logic
        for k, v in results['qsd'].items():
            if not k.strip('+-') in results['qsd+'].keys():
                params[unquote_plus(k)] = unquote_plus(v)

        # Determine Authentication
        auth = ''
        if results.get('user') and results.get('password'):
            auth = (unquote_plus(results.get('user')), unquote_plus(results.get('user')))
        elif results.get('user'):
            auth = (unquote_plus(results.get('user')))

    if '{' in body[:100]:
        try:
            # Try to auto-guess if it's JSON
            h = 'application/json; charset=utf-8'
            json.loads(body)
            headers['Content-Type'] = h
        except ValueError as e:
            logger.warning(f"Could not automatically add '{h}' header to the notification because the document failed to parse as JSON: {e}")
            pass
    status_str = ''

    try:

        r = requests_method(url,
          auth=auth,
          data=body.encode('utf-8') if type(body) is str else body,
          headers=headers,
          params=params
        )

        if r.status_code not in (requests.codes.created, requests.codes.ok):
            status_str = f"Error sending '{schema}' request to {url} - Status: {r.status_code}: '{r.reason}'"
            logger.error(status_str)
            has_error = True
        else:
            logger.info(f"Sent '{schema}' request to {url}")
            has_error = False

    except requests.RequestException as e:
        status_str = f"Error sending '{schema}' request to {url} - {str(e)}"
        logger.error(status_str)
        has_error = True

    if has_error:
        raise TypeError(status_str)

    return True
