#!/usr/bin/env python3
"""
Simple unit tests for TimeExtension that mimic how safe_jinja.py uses it.
These tests demonstrate that the environment.default_timezone override works
exactly as intended in the actual application code.
"""

import arrow
from jinja2.sandbox import ImmutableSandboxedEnvironment
from changedetectionio.jinja2_custom.extensions.TimeExtension import TimeExtension


def test_default_timezone_override_like_safe_jinja(mocker):
    """
    Test that mirrors exactly how safe_jinja.py uses the TimeExtension.
    This is the simplest demonstration that environment.default_timezone works.
    """
    # Create environment (TimeExtension.__init__ sets default_timezone='UTC')
    jinja2_env = ImmutableSandboxedEnvironment(extensions=[TimeExtension])

    # Override the default timezone - exactly like safe_jinja.py does
    jinja2_env.default_timezone = 'America/New_York'

    # Mock arrow.now to return a fixed time
    fixed_time = arrow.Arrow(2025, 1, 15, 12, 0, 0, tzinfo='America/New_York')
    mock = mocker.patch("changedetectionio.jinja2_custom.extensions.TimeExtension.arrow.now", return_value=fixed_time)

    # Use empty string timezone - should use the overridden default
    template_str = "{% now '' %}"
    output = jinja2_env.from_string(template_str).render()

    # Verify arrow.now was called with the overridden timezone
    mock.assert_called_with('America/New_York')
    assert '2025' in output
    assert 'Jan' in output


def test_default_timezone_not_overridden(mocker):
    """
    Test that without override, the default 'UTC' from __init__ is used.
    """
    # Create environment (TimeExtension.__init__ sets default_timezone='UTC')
    jinja2_env = ImmutableSandboxedEnvironment(extensions=[TimeExtension])

    # DON'T override - should use 'UTC' default

    # Mock arrow.now
    fixed_time = arrow.Arrow(2025, 1, 15, 17, 0, 0, tzinfo='UTC')
    mock = mocker.patch("changedetectionio.jinja2_custom.extensions.TimeExtension.arrow.now", return_value=fixed_time)

    # Use empty string timezone - should use 'UTC' default
    template_str = "{% now '' %}"
    output = jinja2_env.from_string(template_str).render()

    # Verify arrow.now was called with 'UTC'
    mock.assert_called_with('UTC')
    assert '2025' in output


def test_datetime_format_override_like_safe_jinja(mocker):
    """
    Test that environment.datetime_format can be overridden after creation.
    """
    # Create environment (default format is '%a, %d %b %Y %H:%M:%S')
    jinja2_env = ImmutableSandboxedEnvironment(extensions=[TimeExtension])

    # Override the datetime format
    jinja2_env.datetime_format = '%Y-%m-%d %H:%M:%S'

    # Mock arrow.now
    fixed_time = arrow.Arrow(2025, 1, 15, 14, 30, 45, tzinfo='UTC')
    mocker.patch("changedetectionio.jinja2_custom.extensions.TimeExtension.arrow.now", return_value=fixed_time)

    # Don't specify format - should use overridden default
    template_str = "{% now 'UTC' %}"
    output = jinja2_env.from_string(template_str).render()

    # Should use custom format YYYY-MM-DD HH:MM:SS
    assert output == '2025-01-15 14:30:45'


def test_offset_with_overridden_timezone(mocker):
    """
    Test that offset operations also respect the overridden default_timezone.
    """
    jinja2_env = ImmutableSandboxedEnvironment(extensions=[TimeExtension])

    # Override to use Europe/London
    jinja2_env.default_timezone = 'Europe/London'

    fixed_time = arrow.Arrow(2025, 1, 15, 10, 0, 0, tzinfo='Europe/London')
    mock = mocker.patch("changedetectionio.jinja2_custom.extensions.TimeExtension.arrow.now", return_value=fixed_time)

    # Use offset with empty timezone string
    template_str = "{% now '' + 'hours=2', '%Y-%m-%d %H:%M:%S' %}"
    output = jinja2_env.from_string(template_str).render()

    # Should have called arrow.now with Europe/London
    mock.assert_called_with('Europe/London')
    # Should be 10:00 + 2 hours = 12:00
    assert output == '2025-01-15 12:00:00'


def test_weekday_parameter_converted_to_int(mocker):
    """
    Test that weekday parameter is properly converted from float to int.
    This is important because arrow.shift() requires weekday as int, not float.
    """
    jinja2_env = ImmutableSandboxedEnvironment(extensions=[TimeExtension])

    # Wednesday, Jan 15, 2025
    fixed_time = arrow.Arrow(2025, 1, 15, 12, 0, 0, tzinfo='UTC')
    mocker.patch("changedetectionio.jinja2_custom.extensions.TimeExtension.arrow.now", return_value=fixed_time)

    # Add offset to next Monday (weekday=0)
    template_str = "{% now 'UTC' + 'weekday=0', '%A' %}"
    output = jinja2_env.from_string(template_str).render()

    # Should be Monday
    assert output == 'Monday'


def test_multiple_offset_parameters(mocker):
    """
    Test that multiple offset parameters can be combined in one expression.
    """
    jinja2_env = ImmutableSandboxedEnvironment(extensions=[TimeExtension])

    fixed_time = arrow.Arrow(2025, 1, 15, 10, 30, 45, tzinfo='UTC')
    mocker.patch("changedetectionio.jinja2_custom.extensions.TimeExtension.arrow.now", return_value=fixed_time)

    # Test multiple parameters: days, hours, minutes, seconds
    template_str = "{% now 'UTC' + 'days=1,hours=2,minutes=15,seconds=10', '%Y-%m-%d %H:%M:%S' %}"
    output = jinja2_env.from_string(template_str).render()

    # 2025-01-15 10:30:45 + 1 day + 2 hours + 15 minutes + 10 seconds
    # = 2025-01-16 12:45:55
    assert output == '2025-01-16 12:45:55'
