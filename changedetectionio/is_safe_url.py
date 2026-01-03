"""
URL redirect validation module for preventing open redirect vulnerabilities.

This module provides functionality to safely validate redirect URLs, ensuring they:
1. Point to internal routes only (no external redirects)
2. Are properly normalized (preventing browser parsing differences)
3. Match registered Flask routes (no fake/non-existent pages)
4. Are fully logged for security monitoring

References:
- https://flask-login.readthedocs.io/ (safe redirect patterns)
- https://blog.miguelgrinberg.com/post/the-flask-mega-tutorial-part-v-user-logins
- https://www.pythonkitchen.com/how-prevent-open-redirect-vulnerab-flask/
"""

from urllib.parse import urlparse, urljoin
from flask import request
from loguru import logger


def is_safe_url(target, app):
    """
    Validate that a redirect URL is safe to prevent open redirect vulnerabilities.

    This follows Flask/Werkzeug best practices by ensuring the redirect URL:
    1. Is a relative path starting with exactly one '/'
    2. Does not start with '//' (double-slash attack)
    3. Has no external protocol handlers
    4. Points to a valid registered route in the application
    5. Is properly normalized to prevent browser parsing differences

    Args:
        target: The URL to validate (e.g., '/settings', '/login#top')
        app: The Flask application instance (needed for route validation)

    Returns:
        bool: True if the URL is safe for redirection, False otherwise

    Examples:
        >>> is_safe_url('/settings', app)
        True
        >>> is_safe_url('//evil.com', app)
        False
        >>> is_safe_url('/settings#general', app)
        True
        >>> is_safe_url('/fake-page', app)
        False
    """
    if not target:
        return False

    # Normalize the URL to prevent browser parsing differences
    # Strip whitespace and replace backslashes (which some browsers interpret as forward slashes)
    target = target.strip()
    target = target.replace('\\', '/')

    # First, check if it starts with // or more (double-slash attack)
    if target.startswith('//'):
        logger.warning(f"Blocked redirect attempt with double-slash: {target}")
        return False

    # Parse the URL to check for scheme and netloc
    parsed = urlparse(target)

    # Block any URL with a scheme (http://, https://, javascript:, etc.)
    if parsed.scheme:
        logger.warning(f"Blocked redirect attempt with scheme: {target}")
        return False

    # Block any URL with a network location (netloc)
    # This catches patterns like //evil.com, user@host, etc.
    if parsed.netloc:
        logger.warning(f"Blocked redirect attempt with netloc: {target}")
        return False

    # At this point, we have a relative URL with no scheme or netloc
    # Use urljoin to resolve it and verify it points to the same host
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))

    # Check: ensure the resolved URL has the same netloc as current host
    if not (test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc):
        logger.warning(f"Blocked redirect attempt with mismatched netloc: {target}")
        return False

    # Additional validation: Check if the URL matches a registered route
    # This prevents redirects to non-existent pages or unintended endpoints
    try:
        # Get the path without query string and fragment
        # Fragments (like #general) are automatically stripped by urlparse
        path = parsed.path

        # Create a URL adapter bound to the server name
        adapter = app.url_map.bind(ref_url.netloc)

        # Try to match the path to a registered route
        # This will raise NotFound if the route doesn't exist
        endpoint, values = adapter.match(path, return_rule=False)

        # Block redirects to static file endpoints - these are catch-all routes
        # that would match arbitrary paths, potentially allowing unintended redirects
        if endpoint in ('static_content', 'static', 'static_flags'):
            logger.warning(f"Blocked redirect to static endpoint: {target}")
            return False

        # Successfully matched a valid route
        logger.debug(f"Validated safe redirect to endpoint '{endpoint}': {target}")
        return True

    except Exception as e:
        # Route doesn't exist or can't be matched
        logger.warning(f"Blocked redirect to non-existent route: {target} (error: {e})")
        return False
