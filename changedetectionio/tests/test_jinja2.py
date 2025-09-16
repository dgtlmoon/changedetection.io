#!/usr/bin/env python3

import time
from flask import url_for
from .util import live_server_setup, wait_for_all_checks
from ..notification import default_notification_title, default_notification_body, default_notification_format


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

    # It should report nothing found (no new 'unviewed' class)
    res = client.get(
        url_for("ui.ui_views.preview_page", uuid="first"),
        follow_redirects=True
    )
    assert b'date=2' in res.data

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

    # It should report nothing found (no new 'unviewed' class)
    res = client.get(url_for("watchlist.index"))
    assert b'is invalid and cannot be used' in res.data
    # Some of the spewed output from the subclasses
    assert b'dict_values' not in res.data


def test_jinja2_notification(client, live_server, measure_memory_usage):

    res = client.post(
        url_for("settings.settings_page"),
        data={"application-notification_urls": "posts://127.0.0.1",
              "application-notification_title": "on the {% now  'America/New_York', '%Y-%m-%d' %}",
              "application-notification_body": "on the {% now  'America/New_York', '%Y-%m-%d' %}",
              "application-notification_format": default_notification_format,
              "requests-time_between_check-minutes": 180,
              'application-fetch_backend': "html_requests"},
        follow_redirects=True
    )

    assert b"Settings updated." in res.data
    assert b"Settings updated." in res.data
