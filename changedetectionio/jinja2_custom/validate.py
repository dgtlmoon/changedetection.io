"""
Validate the Jinja2 templates a user can put in a watch's URL, "Link to Open", request body and headers.

Shared by the edit form and the API, so both reject the same broken templates on save instead of
letting the watch fail on every check. Only values that look like Jinja2 (JINJA2_MARKER_PATTERN) are
rendered, the same rule the fetch uses, so literal text such as URL-encoded JSON ({%22) is left alone.
"""
from loguru import logger

from . import JINJA2_MARKER_PATTERN, render as jinja_render


def _render_exception(value):
    """Return the exception raised rendering value as a Jinja2 template, or None if it is fine or not a template."""
    if not isinstance(value, str) or not JINJA2_MARKER_PATTERN.search(value):
        return None
    try:
        jinja_render(template_str=value)
    except Exception as e:
        logger.error(e)
        return e
    return None


def validate_jinja2_fields(url=None, link_to_open=None, body=None, headers=None) -> dict:
    """Render every templated value and collect the failures.

    Returns {field_name: translated error message}, keyed by the watch field name, empty when everything is valid.
    """
    from flask_babel import gettext

    errors = {}

    for field_name, value in (('url', url), ('link_to_open', link_to_open), ('body', body)):
        e = _render_exception(value)
        if isinstance(e, ModuleNotFoundError):
            # incase jinja2_time or others is missing
            errors[field_name] = gettext('Invalid template syntax configuration: %(error)s') % {'error': e}
        elif e:
            errors[field_name] = gettext('Invalid template syntax: %(error)s') % {'error': e}

    for header, value in (headers or {}).items():
        e = _render_exception(value)
        if isinstance(e, ModuleNotFoundError):
            errors['headers'] = gettext('Invalid template syntax configuration: %(error)s') % {'error': e}
        elif e:
            errors['headers'] = gettext('Invalid template syntax in \"%(header)s\" header: %(error)s') % {'header': header, 'error': e}
        if e:
            # Report the first broken header only, by name, so the user knows which one to fix
            break

    return errors
