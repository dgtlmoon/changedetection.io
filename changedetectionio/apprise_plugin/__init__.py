import json
import re
from urllib.parse import unquote_plus

import requests
from apprise.decorators import notify
from apprise.utils.parse import parse_url as apprise_parse_url
from loguru import logger
from requests.structures import CaseInsensitiveDict


def _get_auth(parsed_url: dict) -> str | tuple[str, str]:
    user: str | None = parsed_url.get("user")
    password: str | None = parsed_url.get("password")
    
    if user is not None and password is not None:
        return (unquote_plus(user), unquote_plus(password))
    
    if user is not None:
        return unquote_plus(user)
    
    return ""


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
    title: str,
    notify_type: str,
    meta: dict,
    *args,
    **kwargs,
) -> bool:
    url: str = meta.get("url")
    schema: str = meta.get("schema").lower().strip()

    # Convert /foobar?+some-header=hello to proper header dictionary
    parsed_url: dict[str, str | dict | None] = apprise_parse_url(url)

    headers = CaseInsensitiveDict(
        {unquote_plus(k): unquote_plus(v) for k, v in parsed_url["qsd+"].items()}
    )

    # https://github.com/caronc/apprise/wiki/Notify_Custom_JSON#get-parameter-manipulation
    # In Apprise, it relies on prefixing each request arg with "-", because it uses say &method=update as a flag for apprise
    # but here we are making straight requests, so we need todo convert this against apprise's logic
    params = CaseInsensitiveDict(
        {
            unquote_plus(k): unquote_plus(v)
            for k, v in parsed_url["qsd"].items()
            if k.strip("+-") not in parsed_url["qsd+"]
        }
    )

    auth = _get_auth(parsed_url=parsed_url)

    # If Content-Type is not specified, guess if it's a JSON body
    if headers.get("Content-Type") is None:
        try:
            json.loads(body)
            headers['Content-Type'] = 'application/json; charset=utf-8'
        except ValueError:
            pass

    url = re.sub(rf"^{schema}", "https" if schema.endswith("s") else "http", parsed_url.get("url"))

    status_str = ''
    has_error = False
    method: str = re.sub(r"s$", "", schema).upper()

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
