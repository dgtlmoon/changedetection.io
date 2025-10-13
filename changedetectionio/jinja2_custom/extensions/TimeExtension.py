"""
Jinja2 TimeExtension - Custom date/time handling for templates.

This extension provides the {% now %} tag for Jinja2 templates, offering timezone-aware
date/time formatting with support for time offsets.

Why This Extension Exists:
    The Arrow library has a now() function (arrow.now()), but Jinja2 templates cannot
    directly call Python functions - they need extensions or filters to expose functionality.

    This TimeExtension serves as a Jinja2-to-Arrow bridge that:

    1. Makes Arrow accessible in templates - Jinja2 requires registering functions/tags
       through extensions. You cannot use arrow.now() directly in a template.

    2. Provides template-friendly syntax - Instead of complex Python code, you get clean tags:
       {% now 'UTC' %}
       {% now 'UTC' + 'hours=2' %}
       {% now 'Europe/London', '%Y-%m-%d' %}

    3. Adds convenience features on top of Arrow:
       - Default timezone from environment variable (TZ) or config
       - Default datetime format configuration
       - Offset syntax parsing: 'hours=2,minutes=30' → shift(hours=2, minutes=30)
       - Empty string timezone support to use configured defaults

    4. Maintains security - Works within Jinja2's sandboxed environment so users
       cannot access arbitrary Python code or objects.

    Essentially, this is a Jinja2 wrapper around arrow.now() and arrow.shift() that
    provides user-friendly template syntax while maintaining security.

Basic Usage:
    {% now 'UTC' %}
    # Output: Wed, 09 Dec 2015 23:33:01

Custom Format:
    {% now 'UTC', '%Y-%m-%d %H:%M:%S' %}
    # Output: 2015-12-09 23:33:01

Timezone Support:
    {% now 'America/New_York' %}
    {% now 'Europe/London' %}
    {% now '' %}  # Uses default timezone from environment.default_timezone

Time Offsets (Addition):
    {% now 'UTC' + 'hours=2' %}
    {% now 'UTC' + 'hours=2,minutes=30' %}
    {% now 'UTC' + 'days=1,hours=2,minutes=15,seconds=10' %}

Time Offsets (Subtraction):
    {% now 'UTC' - 'minutes=11' %}
    {% now 'UTC' - 'days=2,minutes=33,seconds=1' %}

Time Offsets with Custom Format:
    {% now 'UTC' + 'hours=2', '%Y-%m-%d %H:%M:%S' %}
    # Output: 2015-12-10 01:33:01

Weekday Support (for finding next/previous weekday):
    {% now 'UTC' + 'weekday=0' %}  # Next Monday (0=Monday, 6=Sunday)
    {% now 'UTC' + 'weekday=4' %}  # Next Friday

Configuration:
    - Default timezone: Set via TZ environment variable or override environment.default_timezone
    - Default format: '%a, %d %b %Y %H:%M:%S' (can be overridden via environment.datetime_format)

Environment Customization:
    from changedetectionio.jinja2_custom import create_jinja_env

    jinja2_env = create_jinja_env()
    jinja2_env.default_timezone = 'America/New_York'  # Override default timezone
    jinja2_env.datetime_format = '%Y-%m-%d %H:%M'      # Override default format

Supported Offset Parameters:
    - years, months, weeks, days
    - hours, minutes, seconds, microseconds
    - weekday (0=Monday through 6=Sunday, must be integer)

Note:
    This extension uses the Arrow library for timezone-aware datetime handling.
    All timezone names should be valid IANA timezone identifiers (e.g., 'America/New_York').
"""
import arrow

from jinja2 import nodes
from jinja2.ext import Extension
import os

class TimeExtension(Extension):
    """
    Jinja2 Extension providing the {% now %} tag for timezone-aware date/time rendering.

    This extension adds two attributes to the Jinja2 environment:
    - datetime_format: Default strftime format string (default: '%a, %d %b %Y %H:%M:%S')
    - default_timezone: Default timezone for rendering (default: TZ env var or 'UTC')

    Both can be overridden after environment creation by setting the attributes directly.
    """

    tags = {'now'}

    def __init__(self, environment):
        """Jinja2 Extension constructor."""
        super().__init__(environment)

        environment.extend(
            datetime_format='%a, %d %b %Y %H:%M:%S',
            default_timezone=os.getenv('TZ', 'UTC').strip()
        )

    def _datetime(self, timezone, operator, offset, datetime_format):
        """
        Get current datetime with time offset applied.

        Args:
            timezone: IANA timezone identifier (e.g., 'UTC', 'America/New_York') or empty string for default
            operator: '+' for addition or '-' for subtraction
            offset: Comma-separated offset parameters (e.g., 'hours=2,minutes=30')
            datetime_format: strftime format string or None to use environment default

        Returns:
            Formatted datetime string with offset applied

        Example:
            _datetime('UTC', '+', 'hours=2,minutes=30', '%Y-%m-%d %H:%M:%S')
            # Returns current time + 2.5 hours
        """
        # Use default timezone if none specified
        if not timezone or timezone == '':
            timezone = self.environment.default_timezone

        d = arrow.now(timezone)

        # parse shift params from offset and include operator
        shift_params = {}
        for param in offset.split(','):
            interval, value = param.split('=')
            shift_params[interval.strip()] = float(operator + value.strip())

        # Fix weekday parameter can not be float
        if 'weekday' in shift_params:
            shift_params['weekday'] = int(shift_params['weekday'])

        d = d.shift(**shift_params)

        if datetime_format is None:
            datetime_format = self.environment.datetime_format
        return d.strftime(datetime_format)

    def _now(self, timezone, datetime_format):
        """
        Get current datetime without any offset.

        Args:
            timezone: IANA timezone identifier (e.g., 'UTC', 'America/New_York') or empty string for default
            datetime_format: strftime format string or None to use environment default

        Returns:
            Formatted datetime string for current time

        Example:
            _now('America/New_York', '%Y-%m-%d %H:%M:%S')
            # Returns current time in New York timezone
        """
        # Use default timezone if none specified
        if not timezone or timezone == '':
            timezone = self.environment.default_timezone

        if datetime_format is None:
            datetime_format = self.environment.datetime_format
        return arrow.now(timezone).strftime(datetime_format)

    def parse(self, parser):
        """
        Parse the {% now %} tag and generate appropriate AST nodes.

        This method is called by Jinja2 when it encounters a {% now %} tag.
        It parses the tag syntax and determines whether to call _now() or _datetime()
        based on whether offset operations (+ or -) are present.

        Supported syntax:
            {% now 'timezone' %}                              -> calls _now()
            {% now 'timezone', 'format' %}                    -> calls _now()
            {% now 'timezone' + 'offset' %}                   -> calls _datetime()
            {% now 'timezone' + 'offset', 'format' %}         -> calls _datetime()
            {% now 'timezone' - 'offset', 'format' %}         -> calls _datetime()

        Args:
            parser: Jinja2 parser instance

        Returns:
            nodes.Output: AST output node containing the formatted datetime string
        """
        lineno = next(parser.stream).lineno

        node = parser.parse_expression()

        if parser.stream.skip_if('comma'):
            datetime_format = parser.parse_expression()
        else:
            datetime_format = nodes.Const(None)

        if isinstance(node, nodes.Add):
            call_method = self.call_method(
                '_datetime',
                [node.left, nodes.Const('+'), node.right, datetime_format],
                lineno=lineno,
            )
        elif isinstance(node, nodes.Sub):
            call_method = self.call_method(
                '_datetime',
                [node.left, nodes.Const('-'), node.right, datetime_format],
                lineno=lineno,
            )
        else:
            call_method = self.call_method(
                '_now',
                [node, datetime_format],
                lineno=lineno,
            )
        return nodes.Output([call_method], lineno=lineno)