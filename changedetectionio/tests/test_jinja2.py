#!/usr/bin/env python3

import time
from flask import url_for
from .util import live_server_setup, wait_for_all_checks
from ..safe_jinja import render
import arrow


def test_setup(client, live_server, measure_memory_usage):
    live_server_setup(live_server)

# If there was only a change in the whitespacing, then we shouldnt have a change detected
def test_jinja2_in_url_query(client, live_server, measure_memory_usage):
    #live_server_setup(live_server)

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

    # It should report nothing found (no new 'unviewed' class)
    res = client.get(
        url_for("ui.ui_views.preview_page", uuid="first"),
        follow_redirects=True
    )
    assert b'date=2' in res.data

# https://techtonics.medium.com/secure-templating-with-jinja2-understanding-ssti-and-jinja2-sandbox-environment-b956edd60456
def test_jinja2_security_url_query(client, live_server, measure_memory_usage):
    #live_server_setup(live_server)

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

    # It should report nothing found (no new 'unviewed' class)
    res = client.get(url_for("watchlist.index"))
    assert b'is invalid and cannot be used' in res.data
    # Some of the spewed output from the subclasses
    assert b'dict_values' not in res.data

def test_timezone(mocker):
    """Verify that timezone is parsed."""

    timezone = 'America/Buenos Aires'
    currentDate = arrow.now(timezone)
    arrowNowMock = mocker.patch("arrow.now")
    arrowNowMock.return_value = currentDate
    finalRender = render(f"{{% now '{timezone}' %}}")

    assert finalRender == currentDate.strftime("%Y-%m-%d")

def test_format(mocker):
    """Verify that format is parsed."""

    timezone = 'utc'
    format = '%d %b %Y %H:%M:%S'
    currentDate = arrow.now(timezone)
    arrowNowMock = mocker.patch("arrow.now")
    arrowNowMock.return_value = currentDate
    finalRender = render(f"{{% now '{timezone}', '{format}' %}}")

    assert finalRender == currentDate.strftime(format)

def test_add_time(mocker):
    """Verify that added time offset can be parsed."""

    timezone = 'utc'
    currentDate = arrow.now(timezone)
    arrowNowMock = mocker.patch("arrow.now")
    arrowNowMock.return_value = currentDate
    finalRender = render(f"{{% now '{timezone}' + 'hours=2,seconds=30' %}}")

    assert finalRender == currentDate.strftime("%Y-%m-%d")

def test_add_weekday(mocker):
    """Verify that added weekday offset can be parsed."""

    timezone = 'utc'
    currentDate = arrow.now(timezone)
    arrowNowMock = mocker.patch("arrow.now")
    arrowNowMock.return_value = currentDate
    finalRender = render(f"{{% now '{timezone}' + 'weekday=1' %}}")

    assert finalRender == currentDate.shift(weekday=1).strftime('%Y-%m-%d')


def test_substract_time(mocker):
    """Verify that substracted time offset can be parsed."""

    timezone = 'utc'
    currentDate = arrow.now(timezone)
    arrowNowMock = mocker.patch("arrow.now")
    arrowNowMock.return_value = currentDate
    finalRender = render(f"{{% now '{timezone}' - 'minutes=11' %}}")

    assert finalRender == currentDate.shift(minutes=-11).strftime("%Y-%m-%d")


def test_offset_with_format(mocker):
    """Verify that offset works together with datetime format."""

    timezone = 'utc'
    currentDate = arrow.now(timezone)
    arrowNowMock = mocker.patch("arrow.now")
    arrowNowMock.return_value = currentDate
    format = '%d %b %Y %H:%M:%S'
    finalRender = render(
        f"{{% now '{timezone}' - 'days=2,minutes=33,seconds=1', '{format}' %}}"
    )

    assert finalRender == currentDate.shift(days=-2, minutes=-33, seconds=-1).strftime(format)