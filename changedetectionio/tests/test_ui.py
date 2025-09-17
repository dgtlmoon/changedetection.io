#!/usr/bin/env python3

from flask import url_for
from .util import set_original_response, set_modified_response, live_server_setup, wait_for_all_checks
from ..forms import REQUIRE_ATLEAST_ONE_TIME_PART_WHEN_NOT_GLOBAL_DEFAULT, REQUIRE_ATLEAST_ONE_TIME_PART_MESSAGE_DEFAULT


def test_recheck_time_field_validation_global_settings(client, live_server):
    """
    Tests that the global settings time field has atleast one value for week/day/hours/minute/seconds etc entered
    class globalSettingsRequestForm(Form):
        time_between_check = RequiredFormField(TimeBetweenCheckForm)
    """
    res = client.post(
        url_for("settings.settings_page"),
        data={
              "requests-time_between_check-weeks": '',
              "requests-time_between_check-days": '',
              "requests-time_between_check-hours": '',
              "requests-time_between_check-minutes": '',
              "requests-time_between_check-seconds": '',
              },
        follow_redirects=True
    )


    assert REQUIRE_ATLEAST_ONE_TIME_PART_MESSAGE_DEFAULT.encode('utf-8') in res.data


def test_recheck_time_field_validation_single_watch(client, live_server):
    """
    Tests that the global settings time field has atleast one value for week/day/hours/minute/seconds etc entered
    class globalSettingsRequestForm(Form):
        time_between_check = RequiredFormField(TimeBetweenCheckForm)
    """
    test_url = url_for('test_endpoint', _external=True)

    # Add our URL to the import page
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "url": test_url,
            'fetch_backend': "html_requests",
            "time_between_check_use_default": "",  # OFF
            "time_between_check-weeks": '',
            "time_between_check-days": '',
            "time_between_check-hours": '',
            "time_between_check-minutes": '',
            "time_between_check-seconds": '',
        },
        follow_redirects=True
    )


    assert REQUIRE_ATLEAST_ONE_TIME_PART_WHEN_NOT_GLOBAL_DEFAULT.encode('utf-8') in res.data

    # Now set some time
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "url": test_url,
            'fetch_backend': "html_requests",
            "time_between_check_use_default": "",  # OFF
            "time_between_check-weeks": '',
            "time_between_check-days": '',
            "time_between_check-hours": '',
            "time_between_check-minutes": '5',
            "time_between_check-seconds": '',
        },
        follow_redirects=True
    )

    assert b"Updated watch." in res.data
    assert REQUIRE_ATLEAST_ONE_TIME_PART_WHEN_NOT_GLOBAL_DEFAULT.encode('utf-8') not in res.data

    # Now set to use defaults
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "url": test_url,
            'fetch_backend': "html_requests",
            "time_between_check_use_default": "y",  # ON YES
            "time_between_check-weeks": '',
            "time_between_check-days": '',
            "time_between_check-hours": '',
            "time_between_check-minutes": '',
            "time_between_check-seconds": '',
        },
        follow_redirects=True
    )

    assert b"Updated watch." in res.data
    assert REQUIRE_ATLEAST_ONE_TIME_PART_WHEN_NOT_GLOBAL_DEFAULT.encode('utf-8') not in res.data

def test_checkbox_open_diff_in_new_tab(client, live_server):
    
    set_original_response()
    # Add our URL to the import page
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": url_for('test_endpoint', _external=True)},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data
    wait_for_all_checks(client)

    # Make a change
    set_modified_response()

    # Test case 1 - checkbox is enabled in settings
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-ui-open_diff_in_new_tab": "1"},
        follow_redirects=True
    )
    assert b'Settings updated' in res.data

    # Force recheck
    res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    assert b'Queued 1 watch for rechecking.' in res.data

    wait_for_all_checks(client)
    
    res = client.get(url_for("watchlist.index"))
    lines = res.data.decode().split("\n")

    # Find link to diff page
    target_line = None
    for line in lines:
        if '/diff' in line:
            target_line = line.strip()
            break

    assert target_line != None
    assert 'target=' in target_line

    # Test case 2 - checkbox is disabled in settings
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-ui-open_diff_in_new_tab": ""},
        follow_redirects=True
    )
    assert b'Settings updated' in res.data

    # Force recheck
    res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    assert b'Queued 1 watch for rechecking.' in res.data

    wait_for_all_checks(client)
    
    res = client.get(url_for("watchlist.index"))
    lines = res.data.decode().split("\n")

    # Find link to diff page
    target_line = None
    for line in lines:
        if '/diff' in line:
            target_line = line.strip()
            break

    assert target_line != None
    assert 'target=' not in target_line

    # Cleanup everything
    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

def test_page_title_listing_behaviour(client, live_server):

    set_original_response(extra_title="custom html")

    # either the manually entered title/description or the page link should be visible
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-ui-use_page_title_in_list": "",
              "requests-time_between_check-minutes": 180,
              'application-fetch_backend': "html_requests"},
        follow_redirects=True
    )
    assert b"Settings updated." in res.data


    # Add our URL to the import page
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": url_for('test_endpoint', _external=True)},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data
    wait_for_all_checks(client)

    # We see the URL only, no title/description was manually entered
    res = client.get(url_for("watchlist.index"))
    assert url_for('test_endpoint', _external=True).encode('utf-8') in res.data


    # Now 'my title' should override
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
        "url": url_for('test_endpoint', _external=True),
        "title": "my title",
        "fetch_backend": "html_requests",
        "time_between_check_use_default": "y"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    res = client.get(url_for("watchlist.index"))
    assert b"my title" in res.data

    # Now we enable page <title> and unset the override title/description
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-ui-use_page_title_in_list": "y",
              "requests-time_between_check-minutes": 180,
              'application-fetch_backend': "html_requests"},
        follow_redirects=True
    )
    assert b"Settings updated." in res.data

    # Page title description override should take precedence
    res = client.get(url_for("watchlist.index"))
    assert b"my title" in res.data

    # Remove page title description override and it should fall back to title
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
        "url": url_for('test_endpoint', _external=True),
        "title": "",
        "fetch_backend": "html_requests",
        "time_between_check_use_default": "y"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    # No page title description, and 'use_page_title_in_list' is on, it should show the <title>
    res = client.get(url_for("watchlist.index"))
    assert b"head titlecustom html" in res.data

