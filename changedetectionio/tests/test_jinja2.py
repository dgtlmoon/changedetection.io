#!/usr/bin/env python3

import time
import arrow
from flask import url_for
from .util import live_server_setup, wait_for_all_checks
from ..safe_jinja import render


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
    arrowNowMock = mocker.patch("changedetectionio.jinja_extensions.arrow.now")
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
    arrowNowMock = mocker.patch("changedetectionio.jinja_extensions.arrow.now")
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