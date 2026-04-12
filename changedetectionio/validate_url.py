import ipaddress
import socket
from functools import lru_cache
from loguru import logger
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode


def normalize_url_encoding(url):
    """
    Safely encode a URL's query parameters, regardless of whether they're already encoded.

    Why this is necessary:
    URLs can arrive in various states - some with already encoded query parameters (%20 for spaces),
    some with unencoded parameters (literal spaces), or a mix of both. The validators.url() function
    requires proper encoding, but simply encoding an already-encoded URL would double-encode it
    (e.g., %20 would become %2520).

    This function solves the problem by:
    1. Parsing the URL to extract query parameters
    2. parse_qsl() automatically decodes parameters if they're encoded
    3. urlencode() re-encodes them properly
    4. Returns a consistently encoded URL that will pass validation

    Example:
    - Input:  "http://example.com/test?time=2025-10-28 09:19"  (space not encoded)
    - Output: "http://example.com/test?time=2025-10-28+09%3A19" (properly encoded)

    - Input:  "http://example.com/test?time=2025-10-28%2009:19" (already encoded)
    - Output: "http://example.com/test?time=2025-10-28+09%3A19" (properly encoded)

    Returns a properly encoded URL string.
    """
    try:
        # Parse the URL into components (scheme, netloc, path, params, query, fragment)
        parsed = urlparse(url)

        # Parse query string - this automatically decodes it if encoded
        # parse_qsl handles both encoded and unencoded query strings gracefully
        query_params = parse_qsl(parsed.query, keep_blank_values=True)

        # Re-encode the query string properly using standard URL encoding
        encoded_query = urlencode(query_params, safe='')

        # Reconstruct the URL with properly encoded query string
        normalized = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            encoded_query,  # Use the re-encoded query
            parsed.fragment
        ))

        return normalized
    except Exception as e:
        # If parsing fails for any reason, return original URL
        logger.debug(f"URL normalization failed for '{url}': {e}")
        return url


def is_private_hostname(hostname):
    """Return True if hostname resolves to an IANA-restricted (private/reserved) IP address.

    Unresolvable hostnames return False (allow them) — DNS may be temporarily unavailable
    or the domain not yet live. The actual DNS rebinding attack is mitigated by fetch-time
    re-validation in requests.py, not by blocking unresolvable domains at add-time.
    Never cached — callers that need fresh DNS resolution (e.g. at fetch time) can call
    this directly without going through the lru_cached is_safe_valid_url().
    """
    try:
        for info in socket.getaddrinfo(hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                logger.warning(f"Hostname '{hostname} - {ip} - ip.is_private = {ip.is_private}, ip.is_loopback = {ip.is_loopback}, ip.is_link_local = {ip.is_link_local}, ip.is_reserved = {ip.is_reserved}")
                return True
    except socket.gaierror as e:
        logger.warning(f"{hostname} error checking {str(e)}")
        return False
    logger.info(f"Hostname '{hostname}' is NOT private/IANA restricted.")
    return False


def is_safe_valid_url(test_url):
    from changedetectionio import strtobool
    from changedetectionio.jinja2_custom import render as jinja_render
    import os
    import re
    import validators

    # Validate input type first - must be a non-empty string
    if test_url is None:
        logger.warning('URL validation failed: URL is None')
        return False

    if not isinstance(test_url, str):
        logger.warning(f'URL validation failed: URL must be a string, got {type(test_url).__name__}')
        return False

    if not test_url.strip():
        logger.warning('URL validation failed: URL is empty or whitespace only')
        return False

    # Per-request cache: same URL is often validated 2-3x per watchlist render (sort + display).
    # Flask's g is scoped to one request and auto-cleared on teardown, so dynamic Jinja2 URLs
    # like {{microtime()}} are always re-evaluated on the next request.
    # Falls back gracefully when called outside a request context (e.g. background workers).
    _cache_key = test_url
    try:
        from flask import g
        _cache = g.setdefault('_url_validation_cache', {})
        if _cache_key in _cache:
            return _cache[_cache_key]
    except RuntimeError:
        _cache = None  # No app context

    allow_file_access = strtobool(os.getenv('ALLOW_FILE_URI', 'false'))
    safe_protocol_regex = '^(http|https|ftp|file):' if allow_file_access else '^(http|https|ftp):'

    # See https://github.com/dgtlmoon/changedetection.io/issues/1358

    # Remove 'source:' prefix so we dont get 'source:javascript:' etc
    # 'source:' is a valid way to tell us to return the source

    r = re.compile('^source:', re.IGNORECASE)
    test_url = r.sub('', test_url)

    # Check the actual rendered URL in case of any Jinja markup
    # Only run jinja_render when the URL actually contains Jinja2 syntax - creating a new
    # ImmutableSandboxedEnvironment is expensive and is called once per watch per page load
    if '{%' in test_url or '{{' in test_url:
        try:
            test_url = jinja_render(test_url)
        except Exception as e:
            logger.error(f'URL "{test_url}" is not correct Jinja2? {str(e)}')
            return False

    # Check query parameters and fragment
    if re.search(r'[<>]', test_url):
        logger.warning(f'URL "{test_url}" contains suspicious characters')
        return False

    # Normalize URL encoding - handle both encoded and unencoded query parameters
    test_url = normalize_url_encoding(test_url)

    # Be sure the protocol is safe (no file, etcetc)
    pattern = re.compile(os.getenv('SAFE_PROTOCOL_REGEX', safe_protocol_regex), re.IGNORECASE)
    if not pattern.match(test_url.strip()):
        logger.warning(f'URL "{test_url}" is not safe, aborting.')
        return False

    # If hosts that only contain alphanumerics are allowed ("localhost" for example)
    allow_simplehost = not strtobool(os.getenv('BLOCK_SIMPLEHOSTS', 'False'))
    try:
        if not test_url.strip().lower().startswith('file:') and not validators.url(test_url, simple_host=allow_simplehost):
            logger.warning(f'URL "{test_url}" failed validation, aborting.')
            return False
    except validators.ValidationError:
        logger.warning(f'URL f"{test_url}" failed validation, aborting.')
        return False

    if _cache is not None:
        _cache[_cache_key] = True
    return True
