"""
Optional application-layer protection (rate limiting, IP allow list, query/path/header attack filtering)
using the flaskapi-guard Flask extension. Off by default, switched on with FLASKAPI_GUARD_ENABLED=true.

When it is off this module is never imported and flaskapi_guard is never imported.

flaskapi-guard is not in requirements.txt. To use it, install it with the exact pin and switch it on, for example in Docker:
  EXTRA_PACKAGES=flaskapi-guard==4.4.0
  FLASKAPI_GUARD_ENABLED=true

Environment variables (all optional except the switch):
  FLASKAPI_GUARD_ENABLED          true/false, default false
  FLASKAPI_GUARD_RATE_LIMIT       max requests per client IP per 60 seconds, default 600
  FLASKAPI_GUARD_TRUSTED_PROXIES  comma separated IPs/CIDRs allowed to set X-Forwarded-*, default 127.0.0.1,::1
  FLASKAPI_GUARD_ALLOWED_IPS      comma separated IPs/CIDRs, when set ONLY these clients may connect (and are not rate limited)

Scanning skips /api (it has its own API key check, the guard's ban list, allow list and rate limit still apply there)
and /language/auto-detect. /login has its own budget, see LOGIN_RATE_LIMIT.

Request bodies are never scanned (watch settings, filters and notification templates are free text), and
Redis, response security headers, the guard's own CORS handling and the telemetry agent are all disabled.
"""
import os
from ipaddress import ip_address, ip_network

from loguru import logger

from changedetectionio.strtobool import strtobool

DEFAULT_TRUSTED_PROXIES = '127.0.0.1,::1'
DEFAULT_RATE_LIMIT = 600
# Requests per client IP per window to /login. GET (loading the form) counts as well as POST, and every wrong password
# is a POST plus the GET of the redirect back to the form, so this allows about 10 wrong passwords then the right one,
# while an attacker gets about 15 guesses per 5 minutes per IP.
LOGIN_RATE_LIMIT = (30, 300)
# SecurityConfig's own default exclude_paths, which setting the field replaces
DEFAULT_EXCLUDE_PATHS = ['/docs', '/redoc', '/openapi.json', '/openapi.yaml', '/favicon.ico', '/static']

_FORWARDED_ENVIRON_KEYS = (
    'HTTP_X_FORWARDED_FOR',
    'HTTP_X_FORWARDED_PROTO',
    'HTTP_X_FORWARDED_HOST',
    'HTTP_X_FORWARDED_PORT',
    'HTTP_X_FORWARDED_PREFIX',
)


def guard_enabled():
    return strtobool(os.getenv('FLASKAPI_GUARD_ENABLED'))


def _csv_env(name, default=''):
    return tuple(v.strip() for v in os.getenv(name, default).split(',') if v.strip())


def trusted_proxies():
    return _csv_env('FLASKAPI_GUARD_TRUSTED_PROXIES', DEFAULT_TRUSTED_PROXIES)


def restrict_forwarded_headers(wsgi_app):
    """
    WSGI middleware: drop X-Forwarded-* from requests whose TCP peer is not a trusted proxy.

    Must wrap OUTSIDE werkzeug's ProxyFix (USE_X_SETTINGS), which trusts X-Forwarded-For from any peer
    and rewrites REMOTE_ADDR before the guard runs. This makes ProxyFix and the guard trust the same proxies.
    """
    networks = [ip_network(p, strict=False) for p in trusted_proxies()]

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
                    f"add it to FLASKAPI_GUARD_TRUSTED_PROXIES (currently {','.join(trusted_proxies())}). "
                    f"This warning is logged once."
                )
        return wsgi_app(environ, start_response)

    return middleware


def init_guard(app):
    try:
        from flaskapi_guard import FlaskAPIGuard, SecurityConfig
        from guard_core.handlers.suspatterns_handler import ALL_DETECTION_CATEGORIES
    except ImportError as e:
        raise RuntimeError(
            "FLASKAPI_GUARD_ENABLED is set but the flaskapi-guard package is not installed. "
            "Install it with `pip install flaskapi-guard==4.4.0` (Docker: EXTRA_PACKAGES=flaskapi-guard==4.4.0) "
            "or unset FLASKAPI_GUARD_ENABLED."
        ) from e

    allowed_ips = _csv_env('FLASKAPI_GUARD_ALLOWED_IPS')
    config = SecurityConfig(
        enable_redis=False,
        enable_agent=False,
        enable_cors=False,  # flask_cors (see flask_app.py) keeps handling CORS
        security_headers={'enabled': False},  # leave the existing response headers alone
        detection_scan_body=False,  # watch settings, filters and notification templates are free text
        # guard-core 4.4.0 flags a localhost or LAN Referer as "ssrf", which is the Referer of every request when the UI
        # is reached by a LAN IP or localhost (and changedetection.io has its own SSRF protection for watch URLs).
        enabled_detection_categories=frozenset(ALL_DETECTION_CATEGORIES) - {'ssrf'},
        # Setting this REPLACES the library defaults, so they are repeated. Prefix match on whole path segments.
        # /api has its own key check (a bad key gets the app's 403). Bans, allow list and rate limit still apply there.
        exclude_paths=DEFAULT_EXCLUDE_PATHS + ['/api', '/language/auto-detect'],
        endpoint_rate_limits={'/login': LOGIN_RATE_LIMIT},
        rate_limit=int(os.getenv('FLASKAPI_GUARD_RATE_LIMIT', DEFAULT_RATE_LIMIT)),
        rate_limit_window=60,
        trusted_proxies=trusted_proxies(),
        whitelist=allowed_ips or None,
    )
    FlaskAPIGuard(app, config=config)
    logger.info(f"flaskapi-guard is ENABLED ({config.rate_limit} requests/{config.rate_limit_window}s per client IP)")
