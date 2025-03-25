import json
import re
from urllib.parse import unquote_plus

import requests
from apprise.decorators import notify
from apprise.utils.parse import parse_url as apprise_parse_url
from loguru import logger
from requests.structures import CaseInsensitiveDict


@notify(on="get")
@notify(on="gets")
@notify(on="post")
@notify(on="posts")
@notify(on="put")
@notify(on="puts")
@notify(on="delete")
@notify(on="deletes")
@notify(on="patch")
@notify(on="patchs")
@notify(on="head")
@notify(on="heads")
def apprise_custom_api_call_wrapper(
    body: str,
    meta: dict,
    *args,
    **kwargs,
) -> bool:
    url: str = meta.get("url")
    schema: str = meta.get("schema").lower().strip()
    method: str = re.sub(r"s$", "", schema).upper()

    params = CaseInsensitiveDict({}) # Added to requests
    auth = None
    has_error = False

    # Convert /foobar?+some-header=hello to proper header dictionary
    parsed_url: dict[str, str | dict | None] = apprise_parse_url(url)

    # Add our headers that the user can potentially over-ride if they wish
    # to to our returned result set and tidy entries by unquoting them
    headers = CaseInsensitiveDict({unquote_plus(x): unquote_plus(y)
               for x, y in parsed_url['qsd+'].items()})

    # https://github.com/caronc/apprise/wiki/Notify_Custom_JSON#get-parameter-manipulation
    # In Apprise, it relies on prefixing each request arg with "-", because it uses say &method=update as a flag for apprise
    # but here we are making straight requests, so we need todo convert this against apprise's logic
    for k, v in parsed_url['qsd'].items():
        if not k.strip('+-') in parsed_url['qsd+'].keys():
            params[unquote_plus(k)] = unquote_plus(v)

    # Determine Authentication
    auth = ''
    if parsed_url.get('user') and parsed_url.get('password'):
        auth = (unquote_plus(parsed_url.get('user')), unquote_plus(parsed_url.get('user')))
    elif parsed_url.get('user'):
        auth = (unquote_plus(parsed_url.get('user')))

    # If it smells like it could be JSON and no content-type was already set, offer a default content type.
    if body and '{' in body[:100] and not headers.get('Content-Type'):
        json_header = 'application/json; charset=utf-8'
        try:
            # Try if it's JSON
            json.loads(body)
            headers['Content-Type'] = json_header
        except ValueError as e:
            logger.warning(f"Could not automatically add '{json_header}' header to the notification because the document failed to parse as JSON: {e}")
            pass

    # POSTS -> HTTPS etc
    if schema.lower().endswith('s'):
        url = re.sub(rf'^{schema}', 'https', parsed_url.get('url'))
    else:
        url = re.sub(rf'^{schema}', 'http', parsed_url.get('url'))

    status_str = ''
    try:
        r = requests.request(
            method=method,
            url=url,
            auth=auth,
            data=body.encode("utf-8") if type(body) is str else body,
            headers=headers,
            params=params,
        )

        if not (200 <= r.status_code < 300):
            status_str = f"Error sending '{method.upper()}' request to {url} - Status: {r.status_code}: '{r.reason}'"
            logger.error(status_str)
            has_error = True
        else:
            logger.info(f"Sent '{method.upper()}' request to {url}")
            has_error = False

    except requests.RequestException as e:
        status_str = f"Error sending '{method.upper()}' request to {url} - {str(e)}"
        logger.error(status_str)
        has_error = True

    if has_error:
        raise TypeError(status_str)

    return True
