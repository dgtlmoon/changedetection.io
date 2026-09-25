"""
Jinja2 custom extensions and safe rendering utilities.
"""
import re

from .extensions.TimeExtension import TimeExtension
from .safe_jinja import (
    render,
    render_fully_escaped,
    create_jinja_env,
    JINJA2_MAX_RETURN_PAYLOAD_SIZE,
    DEFAULT_JINJA2_EXTENSIONS,
)
from .plugins.regex import regex_replace

JINJA2_MARKER_PATTERN = re.compile(r'{%[-+]?\s*[a-zA-Z_]|{{')

__all__ = [
    'TimeExtension',
    'render',
    'render_fully_escaped',
    'create_jinja_env',
    'JINJA2_MAX_RETURN_PAYLOAD_SIZE',
    'DEFAULT_JINJA2_EXTENSIONS',
    'regex_replace',
    'JINJA2_MARKER_PATTERN',
]
