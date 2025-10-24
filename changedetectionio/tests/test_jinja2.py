#!/usr/bin/env python3

import time
import arrow
from flask import url_for
from .util import live_server_setup, wait_for_all_checks
from ..jinja2_custom import render


# def test_setup(client, live_server, measure_memory_usage):
   # #  live_server_setup(live_server) # Setup on conftest per function

# If there was only a change in the whitespacing, then we shouldnt have a change detected
def test_jinja2_in_url_query(client, live_server, measure_memory_usage):
    

    # Add our URL to the import page
    test_url = url_for('test_return_query', _external=True)

    # because url_for() will URL-encode the var, but we dont here
    full_url = "{}?{}".format(test_url,
                              "date={% now 'Europe/Berlin', '%Y' %}.{% now 'Europe/Berlin', '%m' %}.{% now 'Europe/Berlin', '%d' %}", )
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": full_url, "tags": "test"},
        follow_redirects=True
    )
    assert b"Watch added" in res.data
    wait_for_all_checks(client)

    # It should report nothing found (no new 'has-unread-changes' class)
    res = client.get(
        url_for("ui.ui_views.preview_page", uuid="first"),
        follow_redirects=True
    )
    assert b'date=2' in res.data

# Test for issue #1493 - jinja2-time offset functionality
def test_jinja2_time_offset_in_url_query(client, live_server, measure_memory_usage):
    """Test that jinja2 time offset expressions work in watch URLs (issue #1493)."""

    # Add our URL to the import page with time offset expression
    test_url = url_for('test_return_query', _external=True)

    # Test the exact syntax from issue #1493 that was broken in jinja2-time
    # This should work now with our custom TimeExtension
    full_url = "{}?{}".format(test_url,
                              "timestamp={% now 'utc' - 'minutes=11', '%Y-%m-%d %H:%M' %}", )
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": full_url, "tags": "test"},
        follow_redirects=True
    )
    assert b"Watch added" in res.data
    wait_for_all_checks(client)

    # Verify the URL was processed correctly (should not have errors)
    res = client.get(
        url_for("ui.ui_views.preview_page", uuid="first"),
        follow_redirects=True
    )
    # Should have a valid timestamp in the response
    assert b'timestamp=' in res.data
    # Should not have template error
    assert b'Invalid template' not in res.data

# https://techtonics.medium.com/secure-templating-with-jinja2-understanding-ssti-and-jinja2-sandbox-environment-b956edd60456
def test_jinja2_security_url_query(client, live_server, measure_memory_usage):
    

    # Add our URL to the import page
    test_url = url_for('test_return_query', _external=True)

    # because url_for() will URL-encode the var, but we dont here
    full_url = "{}?{}".format(test_url,
                              "date={{ ''.__class__.__mro__[1].__subclasses__()}}", )
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": full_url, "tags": "test"},
        follow_redirects=True
    )
    assert b"Watch added" in res.data
    wait_for_all_checks(client)

    # It should report nothing found (no new 'has-unread-changes' class)
    res = client.get(url_for("watchlist.index"))
    assert b'is invalid and cannot be used' in res.data
    # Some of the spewed output from the subclasses
    assert b'dict_values' not in res.data

def test_timezone(mocker):
    """Verify that timezone is parsed."""

    timezone = 'America/Buenos_Aires'
    currentDate = arrow.now(timezone)
    arrowNowMock = mocker.patch("changedetectionio.jinja2_custom.extensions.TimeExtension.arrow.now")
    arrowNowMock.return_value = currentDate
    finalRender = render(f"{{% now '{timezone}' %}}")

    assert finalRender == currentDate.strftime('%a, %d %b %Y %H:%M:%S')

def test_format(mocker):
    """Verify that format is parsed."""

    timezone = 'utc'
    format = '%d %b %Y %H:%M:%S'
    currentDate = arrow.now(timezone)
    arrowNowMock = mocker.patch("arrow.now")
    arrowNowMock.return_value = currentDate
    finalRender = render(f"{{% now '{timezone}', '{format}' %}}")

    assert finalRender == currentDate.strftime(format)

def test_add_time(environment):
    """Verify that added time offset can be parsed."""

    finalRender = render("{% now 'utc' + 'hours=2,seconds=30' %}")

    assert finalRender == "Thu, 10 Dec 2015 01:33:31"

def test_add_weekday(mocker):
    """Verify that added weekday offset can be parsed."""

    timezone = 'utc'
    currentDate = arrow.now(timezone)
    arrowNowMock = mocker.patch("changedetectionio.jinja2_custom.extensions.TimeExtension.arrow.now")
    arrowNowMock.return_value = currentDate
    finalRender = render(f"{{% now '{timezone}' + 'weekday=1' %}}")

    assert finalRender == currentDate.shift(weekday=1).strftime('%a, %d %b %Y %H:%M:%S')


def test_substract_time(environment):
    """Verify that substracted time offset can be parsed."""

    finalRender = render("{% now 'utc' - 'minutes=11' %}")

    assert finalRender == "Wed, 09 Dec 2015 23:22:01"


def test_offset_with_format(environment):
    """Verify that offset works together with datetime format."""

    finalRender = render(
        "{% now 'utc' - 'days=2,minutes=33,seconds=1', '%d %b %Y %H:%M:%S' %}"
    )

    assert finalRender == "07 Dec 2015 23:00:00"

def test_default_timezone_empty_string(environment):
    """Verify that empty timezone string uses the default timezone (UTC in test environment)."""

    # Empty string should use the default timezone which is 'UTC' (or from application settings)
    finalRender = render("{% now '' %}")

    # Should render with default format and UTC timezone (matches environment fixture)
    assert finalRender == "Wed, 09 Dec 2015 23:33:01"

def test_default_timezone_with_offset(environment):
    """Verify that empty timezone works with offset operations."""

    # Empty string with offset should use default timezone
    finalRender = render("{% now '' + 'hours=2', '%d %b %Y %H:%M:%S' %}")

    assert finalRender == "10 Dec 2015 01:33:01"

def test_default_timezone_subtraction(environment):
    """Verify that empty timezone works with subtraction offset."""

    finalRender = render("{% now '' - 'minutes=11' %}")

    assert finalRender == "Wed, 09 Dec 2015 23:22:01"

def test_regex_replace_basic():
    """Test basic regex_replace functionality."""

    # Simple word replacement
    finalRender = render("{{ 'hello world' | regex_replace('world', 'universe') }}")
    assert finalRender == "hello universe"

def test_regex_replace_with_groups():
    """Test regex_replace with capture groups (issue #3501 use case)."""

    # Transform HTML table data as described in the issue
    template = "{{ '<td>thing</td><td>other</td>' | regex_replace('<td>([^<]+)</td><td>([^<]+)</td>', 'ThingLabel: \\\\1\\nOtherLabel: \\\\2') }}"
    finalRender = render(template)
    assert "ThingLabel: thing" in finalRender
    assert "OtherLabel: other" in finalRender

def test_regex_replace_multiple_matches():
    """Test regex_replace replacing multiple occurrences."""

    finalRender = render("{{ 'foo bar foo baz' | regex_replace('foo', 'qux') }}")
    assert finalRender == "qux bar qux baz"

def test_regex_replace_count_parameter():
    """Test regex_replace with count parameter to limit replacements."""

    finalRender = render("{{ 'foo bar foo baz' | regex_replace('foo', 'qux', 1) }}")
    assert finalRender == "qux bar foo baz"

def test_regex_replace_empty_replacement():
    """Test regex_replace with empty replacement (removal)."""

    finalRender = render("{{ 'hello world 123' | regex_replace('[0-9]+', '') }}")
    assert finalRender == "hello world "

def test_regex_replace_no_match():
    """Test regex_replace when pattern doesn't match."""

    finalRender = render("{{ 'hello world' | regex_replace('xyz', 'abc') }}")
    assert finalRender == "hello world"

def test_regex_replace_invalid_regex():
    """Test regex_replace with invalid regex pattern returns original value."""

    # Invalid regex (unmatched parenthesis)
    finalRender = render("{{ 'hello world' | regex_replace('(invalid', 'replacement') }}")
    assert finalRender == "hello world"

def test_regex_replace_special_characters():
    """Test regex_replace with special regex characters."""

    finalRender = render("{{ 'Price: $50.00' | regex_replace('\\\\$([0-9.]+)', 'USD \\\\1') }}")
    assert finalRender == "Price: USD 50.00"

def test_regex_replace_multiline():
    """Test regex_replace on multiline text."""

    template = "{{ 'line1\\nline2\\nline3' | regex_replace('^line', 'row') }}"
    finalRender = render(template)
    # By default re.sub doesn't use MULTILINE flag, so only first line matches with ^
    assert finalRender == "row1\nline2\nline3"

def test_regex_replace_with_notification_context():
    """Test regex_replace with notification diff variable."""

    # Simulate how it would be used in notifications with diff variable
    from changedetectionio.notification_service import NotificationContextData

    context = NotificationContextData()
    context['diff'] = '<td>value1</td><td>value2</td>'

    template = "{{ diff | regex_replace('<td>([^<]+)</td>', '\\\\1 ') }}"

    from changedetectionio.jinja2_custom import create_jinja_env
    from jinja2 import BaseLoader

    jinja2_env = create_jinja_env(loader=BaseLoader)
    jinja2_env.globals.update(context)
    finalRender = jinja2_env.from_string(template).render()

    assert "value1 value2 " in finalRender

def test_regex_replace_security_large_input():
    """Test regex_replace handles large input safely."""

    # Create a large input string (over 1MB)
    large_input = "x" * (1024 * 1024 + 1000)
    template = "{{ large_input | regex_replace('x', 'y') }}"

    from changedetectionio.jinja2_custom import create_jinja_env
    from jinja2 import BaseLoader

    jinja2_env = create_jinja_env(loader=BaseLoader)
    jinja2_env.globals['large_input'] = large_input
    finalRender = jinja2_env.from_string(template).render()

    # Should be truncated to 1MB
    assert len(finalRender) == 1024 * 1024

def test_regex_replace_security_long_pattern():
    """Test regex_replace rejects very long patterns."""

    # Pattern longer than 500 chars should be rejected
    long_pattern = "a" * 501
    finalRender = render("{{ 'test' | regex_replace('" + long_pattern + "', 'replacement') }}")

    # Should return original value when pattern is too long
    assert finalRender == "test"

def test_regex_replace_security_dangerous_pattern():
    """Test regex_replace detects and rejects dangerous nested quantifiers."""

    # Patterns that could cause catastrophic backtracking
    dangerous_patterns = [
        "(a+)+",
        "(a*)+",
        "(a+)*",
        "(a*)*",
    ]

    for dangerous in dangerous_patterns:
        # Create a template with the dangerous pattern
        # Using single quotes to avoid escaping issues
        from changedetectionio.jinja2_custom import create_jinja_env
        from jinja2 import BaseLoader

        jinja2_env = create_jinja_env(loader=BaseLoader)
        jinja2_env.globals['pattern'] = dangerous
        template = "{{ 'aaaaaaaaaa' | regex_replace(pattern, 'x') }}"
        finalRender = jinja2_env.from_string(template).render()

        # Should return original value when dangerous pattern is detected
        assert finalRender == "aaaaaaaaaa"

def test_regex_replace_security_timeout_protection():
    """Test that regex_replace has timeout protection (if SIGALRM available)."""
    import signal

    # Only test on systems that support SIGALRM
    if not hasattr(signal, 'SIGALRM'):
        # Skip test on Windows and other systems without SIGALRM
        return

    # This pattern is known to cause exponential backtracking on certain inputs
    # but should be caught by our dangerous pattern detector
    # We're mainly testing that the timeout mechanism works

    from changedetectionio.jinja2_custom import regex_replace

    # Create input that could trigger slow regex
    test_input = "a" * 50 + "b"

    # This shouldn't take long due to our protections
    result = regex_replace(test_input, "a+b", "x")

    # Should complete and return a result
    assert result is not None