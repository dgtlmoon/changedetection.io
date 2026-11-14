"""
Limit which TCP peers may set X-Forwarded-* when USE_X_SETTINGS is on.

werkzeug's ProxyFix (USE_X_SETTINGS) trusts X-Forwarded-* from ANY peer. With a list of trusted proxies, the headers
are dropped from every other peer before ProxyFix sees them.

  USE_X_SETTINGS_TRUSTED_PROXIES  comma separated IPs/CIDRs allowed to set X-Forwarded-*, default unset (any peer)

With flaskapi-guard on (see guard.py) and this unset, FLASKAPI_GUARD_TRUSTED_PROXIES is used instead, so ProxyFix and
the guard trust the same proxies and the guard's client IP cannot be spoofed.
"""
import os
from ipaddress import ip_address, ip_network

from loguru import logger

SETTING = 'USE_X_SETTINGS_TRUSTED_PROXIES'

_FORWARDED_ENVIRON_KEYS = (
    'HTTP_X_FORWARDED_FOR',
    'HTTP_X_FORWARDED_PROTO',
    'HTTP_X_FORWARDED_HOST',
    'HTTP_X_FORWARDED_PORT',
    'HTTP_X_FORWARDED_PREFIX',
)


def restrict_forwarded_headers(wsgi_app, trusted_proxies, setting_name):
    """
    WSGI middleware: drop X-Forwarded-* from requests whose TCP peer is not in trusted_proxies (IPs/CIDRs).

    Must wrap OUTSIDE werkzeug's ProxyFix, which rewrites REMOTE_ADDR from X-Forwarded-For.
    setting_name is the env var the list came from, it is named in the warning.
    """
    networks = [ip_network(p, strict=False) for p in trusted_proxies]

    def is_trusted(peer):
        try:
            return any(ip_address(peer) in net for net in networks)
        except ValueError:
            return False

    warned = False

    def middleware(environ, start_response):
        nonlocal warned
        peer = environ.get('REMOTE_ADDR', '')
        if not is_trusted(peer):
            dropped = [key for key in _FORWARDED_ENVIRON_KEYS if environ.pop(key, None) is not None]
            if dropped and not warned:
                warned = True  # once per process, no log flood
                logger.warning(
                    f"Ignoring X-Forwarded-* headers from {peer}, it is not a trusted proxy. If it is your reverse proxy, "
                    f"add it to {setting_name} (currently {','.join(trusted_proxies)}). "
                    f"This warning is logged once."
                )
        return wsgi_app(environ, start_response)

    return middleware


def restrict_proxy_fix_trust(wsgi_app, guard_on):
    """Wrap wsgi_app (which already has ProxyFix) so only trusted proxies may set X-Forwarded-*, if any are configured."""
    own = tuple(v.strip() for v in os.getenv(SETTING, '').split(',') if v.strip())
    if own:
        return restrict_forwarded_headers(wsgi_app, own, SETTING)
    if guard_on:
        from changedetectionio.guard import trusted_proxies
        return restrict_forwarded_headers(wsgi_app, trusted_proxies(), 'FLASKAPI_GUARD_TRUSTED_PROXIES')
    logger.warning(
        f"USE_X_SETTINGS is on and X-Forwarded-* headers are accepted from any client. "
        f"Set {SETTING} to your reverse proxy's IP or CIDR to accept them only from it."
    )
    return wsgi_app
