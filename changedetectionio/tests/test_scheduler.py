#!/usr/bin/env python3

import time
from copy import copy
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from flask import url_for
from .util import  live_server_setup, wait_for_all_checks, extract_UUID_from_client, delete_all_watches
from ..forms import REQUIRE_ATLEAST_ONE_TIME_PART_MESSAGE_DEFAULT, REQUIRE_ATLEAST_ONE_TIME_PART_WHEN_NOT_GLOBAL_DEFAULT


# def test_setup(client, live_server, measure_memory_usage, datastore_path):
   #  live_server_setup(live_server) # Setup on conftest per function

def test_check_basic_scheduler_functionality(client, live_server, measure_memory_usage, datastore_path):
    
    days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    test_url = url_for('test_random_content_endpoint', _external=True)

    # We use "Pacific/Kiritimati" because its the furthest +14 hours, so it might show up more interesting bugs
    # The rest of the actual functionality should be covered in the unit-test  unit/test_scheduler.py
    #####################
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-empty_pages_are_a_change": "",
              "requests-time_between_check-seconds": 1,
              "application-scheduler_timezone_default": "Pacific/Kiritimati",  # Most Forward Time Zone (UTC+14:00)
              'application-fetch_backend': "html_requests"},
        follow_redirects=True
    )

    assert b"Settings updated." in res.data

    res = client.get(url_for("settings.settings_page"))
    assert b'Pacific/Kiritimati' in res.data

    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))

    # Setup all the days of the weeks using XXX as the placeholder for monday/tuesday/etc
    last_check = copy(live_server.app.config['DATASTORE'].data['watching'][uuid]['last_checked'])
    tpl = {
        "time_schedule_limit-XXX-start_time": "00:00",
        "time_schedule_limit-XXX-duration-hours": 24,
        "time_schedule_limit-XXX-duration-minutes": 0,
        "time_between_check-seconds": 1,
        "time_schedule_limit-XXX-enabled": '',  # All days are turned off
        "time_schedule_limit-enabled": 'y',  # Scheduler is enabled, all days however are off.
    }

    scheduler_data = {}
    for day in days:
        for key, value in tpl.items():
            # Replace "XXX" with the current day in the key
            new_key = key.replace("XXX", day)
            scheduler_data[new_key] = value

    data = {
        "url": test_url,
        "fetch_backend": "html_requests",
        "time_between_check_use_default": "" # no
    }
    data.update(scheduler_data)
    time.sleep(1)
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid),
        data=data,
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    res = client.get(url_for("ui.ui_edit.edit_page", uuid=uuid))
    assert b"Pacific/Kiritimati" in res.data, "Should be Pacific/Kiritimati in placeholder data"

    # "Edit" should not trigger a check because it's not enabled in the schedule.
    time.sleep(2)
    # "time_schedule_limit-XXX-enabled": '',  # All days are turned off, therefor, nothing should happen here..
    assert live_server.app.config['DATASTORE'].data['watching'][uuid]['last_checked'] == last_check

    # Enabling today in Kiritimati should work flawless
    kiritimati_time = datetime.now(timezone.utc).astimezone(ZoneInfo("Pacific/Kiritimati"))
    kiritimati_time_day_of_week = kiritimati_time.strftime("%A").lower()
    live_server.app.config['DATASTORE'].data['watching'][uuid]["time_schedule_limit"][kiritimati_time_day_of_week]["enabled"] = True
    time.sleep(3)
    assert live_server.app.config['DATASTORE'].data['watching'][uuid]['last_checked'] != last_check

    # Cleanup everything
    delete_all_watches(client)


def test_check_basic_global_scheduler_functionality(client, live_server, measure_memory_usage, datastore_path):
    
    days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    test_url = url_for('test_random_content_endpoint', _external=True)

    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))

    # Setup all the days of the weeks using XXX as the placeholder for monday/tuesday/etc

    tpl = {
        "requests-time_schedule_limit-XXX-start_time": "00:00",
        "requests-time_schedule_limit-XXX-duration-hours": 24,
        "requests-time_schedule_limit-XXX-duration-minutes": 0,
        "requests-time_schedule_limit-XXX-enabled": '',  # All days are turned off
        "requests-time_schedule_limit-enabled": 'y',  # Scheduler is enabled, all days however are off.
    }

    scheduler_data = {}
    for day in days:
        for key, value in tpl.items():
            # Replace "XXX" with the current day in the key
            new_key = key.replace("XXX", day)
            scheduler_data[new_key] = value

    data = {
        "application-empty_pages_are_a_change": "",
        "application-scheduler_timezone_default": "Pacific/Kiritimati",  # Most Forward Time Zone (UTC+14:00)
        'application-fetch_backend': "html_requests",
        "requests-time_between_check-hours": 0,
        "requests-time_between_check-minutes": 0,
        "requests-time_between_check-seconds": 1,
    }
    data.update(scheduler_data)

    #####################
    res = client.post(
        url_for("settings.settings_page"),
        data=data,
        follow_redirects=True
    )

    assert b"Settings updated." in res.data

    res = client.get(url_for("settings.settings_page"))
    assert b'Pacific/Kiritimati' in res.data

    wait_for_all_checks(client)

    # UI Sanity check

    res = client.get(url_for("ui.ui_edit.edit_page", uuid=uuid))
    assert b"Pacific/Kiritimati" in res.data, "Should be Pacific/Kiritimati in placeholder data"

    #### HITTING SAVE SHOULD NOT TRIGGER A CHECK
    last_check = live_server.app.config['DATASTORE'].data['watching'][uuid]['last_checked']
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid),
        data={
            "url": test_url,
            "fetch_backend": "html_requests",
            "time_between_check_use_default": "y"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    time.sleep(2)
    assert live_server.app.config['DATASTORE'].data['watching'][uuid]['last_checked'] == last_check

    # Enabling "today" in Kiritimati time should make the system check that watch
    kiritimati_time = datetime.now(timezone.utc).astimezone(ZoneInfo("Pacific/Kiritimati"))
    kiritimati_time_day_of_week = kiritimati_time.strftime("%A").lower()
    live_server.app.config['DATASTORE'].data['settings']['requests']['time_schedule_limit'][kiritimati_time_day_of_week]["enabled"] = True

    time.sleep(3)
    assert live_server.app.config['DATASTORE'].data['watching'][uuid]['last_checked'] != last_check

    # Cleanup everything
    delete_all_watches(client)


def test_validation_time_interval_field(client, live_server, measure_memory_usage, datastore_path):
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)


    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid),
        data={"trigger_text": 'The golden line',
              "url": test_url,
              'fetch_backend': "html_requests",
              'filter_text_removed': 'y',
              "time_between_check_use_default": ""
              },
        follow_redirects=True
    )

    assert REQUIRE_ATLEAST_ONE_TIME_PART_WHEN_NOT_GLOBAL_DEFAULT.encode('utf-8') in res.data

    # Now set atleast something

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid),
        data={"trigger_text": 'The golden line',
              "url": test_url,
              'fetch_backend': "html_requests",
              "time_between_check-minutes": 1,
              "time_between_check_use_default": ""
              },
        follow_redirects=True
    )

    assert REQUIRE_ATLEAST_ONE_TIME_PART_WHEN_NOT_GLOBAL_DEFAULT.encode('utf-8') not in res.data


