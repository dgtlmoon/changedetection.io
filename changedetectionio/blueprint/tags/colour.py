"""Validation for the user supplied tag colour, which ends up inside a CSS context.

Tag colours are rendered into `<style>` blocks (watch-overview.html and
groups-overview.html). Jinja2's HTML autoescaping does not help there - CSS injection
needs none of the characters it escapes, so a value like

    red} *{background-image:url(https://attacker.example.com/exfil)} .x{color:

would break out of the `background-color:` declaration and inject arbitrary rules for
every user viewing the page.

So only a plain hex colour is accepted - checked on the way in (form + API) and again
on the way out when rendering, so a value stored by an older version can't be rendered
either.
"""

import re

# What <input type="color"> produces (#rrggbb), plus the #rgb shorthand.
CSS_HEX_COLOUR_REGEX = r'^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$'

_RE_CSS_HEX_COLOUR = re.compile(CSS_HEX_COLOUR_REGEX)


def is_safe_css_colour(value) -> bool:
    """True if `value` is a hex colour that is safe to write into a CSS declaration."""
    return isinstance(value, str) and bool(_RE_CSS_HEX_COLOUR.match(value.strip()))


def safe_css_colour(value) -> str:
    """Return `value` as a hex colour, or an empty string when it is not one.

    Used at render time so anything unsafe falls back to the auto-generated colour
    instead of being written into the stylesheet.
    """
    return value.strip() if is_safe_css_colour(value) else ''
