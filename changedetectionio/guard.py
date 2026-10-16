"""
Optional application-layer protection (rate limiting, IP allow list, query/path/header attack filtering)
using the flaskapi-guard Flask extension. Off by default, switched on with FLASKAPI_GUARD_ENABLED=true.

When it is off this module is never imported and flaskapi_guard is never imported.

Environment variables (all optional except the switch):
  FLASKAPI_GUARD_ENABLED          true/false, default false
  FLASKAPI_GUARD_RATE_LIMIT       max requests per client IP per 60 seconds, default 600
  FLASKAPI_GUARD_TRUSTED_PROXIES  comma separated IPs/CIDRs allowed to set X-Forwarded-*, default 127.0.0.1,::1
  FLASKAPI_GUARD_ALLOWED_IPS      comma separated IPs/CIDRs, when set ONLY these clients may connect (and are not rate limited)

Request bodies are never scanned (watch settings, filters and notification templates are free text), and
Redis, response security headers, the guard's own CORS handling and the telemetry agent are all disabled.
"""
import os
from ipaddress import ip_address, ip_network

from loguru import logger

from changedetectionio.strtobool import strtobool

DEFAULT_TRUSTED_PROXIES = '127.0.0.1,::1'
DEFAULT_RATE_LIMIT = 600

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

    def middleware(environ, start_response):
        if not is_trusted(environ.get('REMOTE_ADDR', '')):
            for key in _FORWARDED_ENVIRON_KEYS:
                environ.pop(key, None)
        return wsgi_app(environ, start_response)

    return middleware


def init_guard(app):
    try:
        from flaskapi_guard import FlaskAPIGuard, SecurityConfig
        from guard_core.handlers.suspatterns_handler import ALL_DETECTION_CATEGORIES
    except ImportError as e:
        raise RuntimeError(
            "FLASKAPI_GUARD_ENABLED is set but the flaskapi-guard package is not installed. "
            "Install it with `pip install flaskapi-guard` or unset FLASKAPI_GUARD_ENABLED."
        ) from e

    allowed_ips = _csv_env('FLASKAPI_GUARD_ALLOWED_IPS')
    config = SecurityConfig(
        enable_redis=False,
        enable_agent=False,
        enable_cors=False,  # flask_cors (see flask_app.py) keeps handling CORS
        security_headers={'enabled': False},  # leave the existing response headers alone
        detection_scan_body=False,  # watch settings, filters and notification templates are free text
        # "recon" matches path fragments like /language/ (set-language, language/auto-detect).
        # "ssrf" matches private/LAN/localhost URLs, which is the Referer of every request when the UI is reached
        # by a LAN IP or localhost (and changedetection.io has its own SSRF protection for watch URLs).
        enabled_detection_categories=frozenset(ALL_DETECTION_CATEGORIES) - {'recon', 'ssrf'},
        rate_limit=int(os.getenv('FLASKAPI_GUARD_RATE_LIMIT', DEFAULT_RATE_LIMIT)),
        rate_limit_window=60,
        trusted_proxies=trusted_proxies(),
        whitelist=allowed_ips or None,
    )
    FlaskAPIGuard(app, config=config)
    logger.info(f"flaskapi-guard is ENABLED ({config.rate_limit} requests/{config.rate_limit_window}s per client IP)")
