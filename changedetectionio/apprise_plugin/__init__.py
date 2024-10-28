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
    from urllib.parse import unquote_plus
    from apprise.utils import parse_url as apprise_parse_url
    from apprise import URLBase

    url = kwargs['meta'].get('url')

    if url.startswith('post'):
        r = requests.post
    elif url.startswith('get'):
        r = requests.get
    elif url.startswith('put'):
        r = requests.put
    elif url.startswith('delete'):
        r = requests.delete

    url = url.replace('post://', 'http://')
    url = url.replace('posts://', 'https://')
    url = url.replace('put://', 'http://')
    url = url.replace('puts://', 'https://')
    url = url.replace('get://', 'http://')
    url = url.replace('gets://', 'https://')
    url = url.replace('put://', 'http://')
    url = url.replace('puts://', 'https://')
    url = url.replace('delete://', 'http://')
    url = url.replace('deletes://', 'https://')

    headers = {}
    params = {}
    auth = None

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

    # Try to auto-guess if it's JSON
    h = 'application/json; charset=utf-8'
    try:
        json.loads(body)
        headers['Content-Type'] = h
    except ValueError as e:
        logger.warning(f"Could not automatically add '{h}' header to the {kwargs['meta'].get('schema')}:// notification because the document failed to parse as JSON: {e}")
        pass

    r(results.get('url'),
      auth=auth,
      data=body.encode('utf-8') if type(body) is str else body,
      headers=headers,
      params=params
      )