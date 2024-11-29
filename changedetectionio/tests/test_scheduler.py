#!/usr/bin/env python3

import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from flask import url_for
from .util import set_original_response, set_modified_response, live_server_setup, wait_for_all_checks, extract_rss_token_from_UI, \
    extract_UUID_from_client


def test_check_basic_scheduler_functionality(client, live_server, measure_memory_usage):
    live_server_setup(live_server)
    days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    test_url = url_for('test_random_content_endpoint', _external=True)

    # We use "Pacific/Kiritimati" because its the furthest +14 hours, so it might show up more interesting bugs

    #####################
    res = client.post(
        url_for("settings_page"),
        data={"application-empty_pages_are_a_change": "",
              "requests-time_between_check-seconds": 1,
              "application-timezone": "Pacific/Kiritimati", # Most Forward Time Zone (UTC+14:00)
              'application-fetch_backend': "html_requests"},
        follow_redirects=True
    )

    assert b"Settings updated." in res.data

    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data
    wait_for_all_checks(client)
    uuid = extract_UUID_from_client(client)

    tpl = {
        "time_schedule_limit-XXX-start_time": "00:00",
        "time_schedule_limit-XXX-duration-hours": 24,
        "time_schedule_limit-XXX-duration-minutes": 0,
        "time_schedule_limit-XXX-enabled": '',  # All days are turned off
        "time_schedule_limit-enabled": 'y',  # Scheduler is enabled, all days however are off.
    }

    scheduler_data = {}
    for day in days:
        for key, value in tpl.items():
            # Replace "XXX" with the current day in the key
            new_key = key.replace("XXX", day)
            scheduler_data[new_key] = value

    last_check = live_server.app.config['DATASTORE'].data['watching'][uuid]['last_checked']
    data = {
        "url": test_url,
        "fetch_backend": "html_requests"
    }
    data.update(scheduler_data)

    res = client.post(
        url_for("edit_page", uuid="first"),
        data=data,
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    # "Edit" should not trigger a check because it's not enabled in the schedule.
    time.sleep(2)
    assert live_server.app.config['DATASTORE'].data['watching'][uuid]['last_checked'] == last_check


    # Enabling today in Kiritimati should work flawless
    kiritimati_time = datetime.now(timezone.utc).astimezone(ZoneInfo("Pacific/Kiritimati"))
    kiritimati_time_day_of_week = kiritimati_time.strftime("%A").lower()
    live_server.app.config['DATASTORE'].data['watching'][uuid]["time_schedule_limit"][kiritimati_time_day_of_week]["enabled"] = True
    time.sleep(3)
    assert live_server.app.config['DATASTORE'].data['watching'][uuid]['last_checked'] != last_check


    # Cleanup everything
    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data
