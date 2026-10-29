"""
OAuth 2.0 for watches of APIs that want a bearer token (#375).

A watch with an OAuth token URL and client credentials gets an access token with the client credentials grant
(RFC 6749, section 4.4) and sends it as "Authorization: Bearer ..." with each check. Tokens are cached until shortly
before they expire, shared by every watch that uses the same credentials, and forgotten when the API answers 401, so
the next check asks for a new one.
"""
import threading
import time

from loguru import logger

# Ask for a new token this many seconds before the old one expires, so a check never sends one that runs out on the way
EXPIRY_MARGIN_SECONDS = 30
# For servers that don't say how long a token lasts
DEFAULT_EXPIRES_IN_SECONDS = 300

_cache = {}
_lock = threading.Lock()


class OAuth2Error(Exception):
    pass


def is_configured(watch):
    return bool((watch.get('oauth2_token_url') or '').strip() and (watch.get('oauth2_client_id') or '').strip())


def _settings(watch):
    return {
        'token_url': watch.get('oauth2_token_url').strip(),
        'client_id': watch.get('oauth2_client_id').strip(),
        'client_secret': watch.get('oauth2_client_secret') or '',
        'scope': (watch.get('oauth2_scope') or '').strip(),
        'audience': (watch.get('oauth2_audience') or '').strip(),
        'client_auth': watch.get('oauth2_client_auth') or 'basic',
    }


def _cache_key(settings):
    # The secret is part of the key, so changing it gets a new token rather than a cached one made with the old secret
    return (settings['token_url'], settings['client_id'], settings['client_secret'], settings['scope'], settings['audience'])


def _error_detail(response):
    try:
        data = response.json()
    except ValueError:
        return response.text.strip()[:200] or response.reason
    if isinstance(data, dict):
        parts = [str(data.get('error') or ''), str(data.get('error_description') or '')]
        return ': '.join(p for p in parts if p) or response.reason
    return response.reason


def get_access_token(watch, proxies=None, timeout=30):
    """An access token for the watch's OAuth settings, from the cache when one is still good."""
    import requests

    from changedetectionio.validate_url import is_fetch_url_allowed

    settings = _settings(watch)
    key = _cache_key(settings)

    with _lock:
        cached = _cache.get(key)
        if cached and cached[1] > time.time():
            return cached[0]

    # The token URL is fetched by the server like the watch's own URL, so it passes the same gate
    allowed, reason = is_fetch_url_allowed(settings['token_url'])
    if not allowed:
        raise OAuth2Error(f"OAuth token URL not allowed: {reason}")

    data = {'grant_type': 'client_credentials'}
    if settings['scope']:
        data['scope'] = settings['scope']
    if settings['audience']:
        data['audience'] = settings['audience']

    auth = None
    if settings['client_auth'] == 'body':
        data['client_id'] = settings['client_id']
        data['client_secret'] = settings['client_secret']
    else:
        auth = (settings['client_id'], settings['client_secret'])

    try:
        response = requests.post(settings['token_url'],
                                 data=data,
                                 auth=auth,
                                 headers={'Accept': 'application/json'},
                                 proxies=proxies,
                                 timeout=timeout,
                                 # a redirect would carry the credentials somewhere the gate above never saw
                                 allow_redirects=False)
    except requests.RequestException as e:
        raise OAuth2Error(f"Could not reach the OAuth token URL: {e}") from e

    if response.status_code != 200:
        raise OAuth2Error(f"OAuth token request failed ({response.status_code}): {_error_detail(response)}")

    try:
        payload = response.json()
    except ValueError:
        raise OAuth2Error("OAuth token response was not JSON") from None

    token = payload.get('access_token') if isinstance(payload, dict) else None
    if not token:
        raise OAuth2Error("OAuth token response had no access_token")

    try:
        expires_in = int(payload.get('expires_in') or DEFAULT_EXPIRES_IN_SECONDS)
    except (TypeError, ValueError):
        expires_in = DEFAULT_EXPIRES_IN_SECONDS

    with _lock:
        _cache[key] = (token, time.time() + max(0, expires_in - EXPIRY_MARGIN_SECONDS))

    logger.debug(f"Got an OAuth access token from {settings['token_url']}, good for {expires_in}s")
    return token


def forget_token(watch):
    """Drop the cached token for the watch's settings, after the API refused it."""
    if not is_configured(watch):
        return
    with _lock:
        _cache.pop(_cache_key(_settings(watch)), None)


def clear_cache():
    with _lock:
        _cache.clear()
