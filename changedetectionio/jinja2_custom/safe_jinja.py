"""
Safe Jinja2 render with max payload sizes

See https://jinja.palletsprojects.com/en/3.1.x/sandbox/#security-considerations
"""

import jinja2.sandbox
import typing as t
import os
from .extensions.TimeExtension import TimeExtension
from .plugins import regex_replace

JINJA2_MAX_RETURN_PAYLOAD_SIZE = 1024 * int(os.getenv("JINJA2_MAX_RETURN_PAYLOAD_SIZE_KB", 1024 * 10))

# Default extensions - can be overridden in create_jinja_env()
DEFAULT_JINJA2_EXTENSIONS = [TimeExtension]

def create_jinja_env(extensions=None, **kwargs) -> jinja2.sandbox.ImmutableSandboxedEnvironment:
    """
    Create a sandboxed Jinja2 environment with our custom extensions and default timezone.

    Args:
        extensions: List of extension classes to use (defaults to DEFAULT_JINJA2_EXTENSIONS)
        **kwargs: Additional arguments to pass to ImmutableSandboxedEnvironment

    Returns:
        Configured Jinja2 environment
    """
    if extensions is None:
        extensions = DEFAULT_JINJA2_EXTENSIONS

    jinja2_env = jinja2.sandbox.ImmutableSandboxedEnvironment(
        extensions=extensions,
        **kwargs
    )

    # Get default timezone from environment variable
    default_timezone = os.getenv('TZ', 'UTC').strip()
    jinja2_env.default_timezone = default_timezone

    # Register custom filters
    jinja2_env.filters['regex_replace'] = regex_replace

    return jinja2_env


# This is used for notifications etc, so actually it's OK to send custom HTML such as <a href> etc, but it should limit what data is available.
# (Which also limits available functions that could be called)
def render(template_str, **args: t.Any) -> str:
    jinja2_env = create_jinja_env()
    output = jinja2_env.from_string(template_str).render(args)
    return output[:JINJA2_MAX_RETURN_PAYLOAD_SIZE]

def render_fully_escaped(content):
    """
    Escape HTML content safely.

    MEMORY LEAK FIX: Use markupsafe.escape() directly instead of creating
    Jinja2 environments (was causing 1M+ compilations per page load).
    Simpler, faster, and no concerns about environment state.
    """
    from markupsafe import escape
    return str(escape(content))

