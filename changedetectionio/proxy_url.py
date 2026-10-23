"""
Helpers for proxy URLs that carry credentials.

A username or password containing characters such as `#`, `/`, `?` or `@` has to
be percent-encoded in the URL, otherwise the URL does not parse. Browser fetchers
take the username and password as separate fields, so they need the decoded
values. Anything written to the log gets the credentials removed.
"""

from urllib.parse import unquote, urlparse


def proxy_credentials(proxy_url):
    """Return the decoded (username, password) of a proxy URL, either may be None."""
    if not proxy_url:
        return None, None
    parsed = urlparse(proxy_url)
    username = unquote(parsed.username) if parsed.username is not None else None
    password = unquote(parsed.password) if parsed.password is not None else None
    return username, password


def redact_proxy_url(proxy_url):
    """The proxy URL with its username and password replaced by `***`, for logging."""
    if not proxy_url or '@' not in proxy_url:
        return proxy_url
    scheme, separator, rest = proxy_url.partition('://')
    if not separator:
        scheme, rest = '', proxy_url
    # rpartition: an unencoded `@` or `#` in the password must not leave part of it behind
    host = rest.rpartition('@')[2]
    return f"{scheme}{separator}***@{host}"
