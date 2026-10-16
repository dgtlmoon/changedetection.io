#!/usr/bin/env python3
"""
time_schedule_limit end to end - the edit page, watch.json on disk and the API.

The schedule is a typed model where anything equal to the default is the shared default
instance and only the difference is written to disk, see model/TimeScheduleLimit.py
"""
import json
import os

from flask import url_for

from changedetectionio.model.TimeScheduleLimit import DAYS_OF_WEEK, DEFAULT_TIME_SCHEDULE_LIMIT
from .util import set_original_response, wait_for_all_checks, delete_all_watches


def _edit_form(url, scheduler_enabled=False, tuesday_start="00:00"):
    data = {
        "url": url,
        "fetch_backend": "html_requests",
        "time_between_check_use_default": "y",
    }
    if scheduler_enabled:
        data["time_schedule_limit-enabled"] = 'y'
    for day in DAYS_OF_WEEK:
        data[f"time_schedule_limit-{day}-enabled"] = 'y'
        data[f"time_schedule_limit-{day}-start_time"] = tuesday_start if day == 'tuesday' else "00:00"
        data[f"time_schedule_limit-{day}-duration-hours"] = 24
        data[f"time_schedule_limit-{day}-duration-minutes"] = 0
    return data


def _stored_schedule(watch):
    with open(os.path.join(watch.data_dir, 'watch.json')) as f:
        return json.load(f).get('time_schedule_limit')


def test_edit_page_schedule_storage(client, live_server, measure_memory_usage, datastore_path):
    set_original_response(datastore_path=datastore_path)
    test_url = url_for('test_endpoint', _external=True)
    datastore = live_server.app.config['DATASTORE']
    # The scheduler part of the edit page only renders once a default timezone is configured
    datastore.data['settings']['application']['scheduler_timezone_default'] = 'UTC'
    uuid = datastore.add_watch(url=test_url)
    wait_for_all_checks(client)

    # The edit page renders the default week from the shared default
    res = client.get(url_for("ui.ui_edit.edit_page", uuid=uuid))
    assert res.status_code == 200
    assert b'name="time_schedule_limit-monday-duration-hours"' in res.data
    assert b'<option selected value="24">24</option>' in res.data

    # Saving the untouched week is no change - shared default in memory, nothing on disk
    res = client.post(url_for("ui.ui_edit.edit_page", uuid=uuid), data=_edit_form(test_url), follow_redirects=True)
    assert b"Updated watch." in res.data
    watch = datastore.data['watching'][uuid]
    assert watch['time_schedule_limit'] is DEFAULT_TIME_SCHEDULE_LIMIT
    assert _stored_schedule(watch) == {}

    # Enabled with the default days is their setting, kept
    client.post(url_for("ui.ui_edit.edit_page", uuid=uuid), data=_edit_form(test_url, scheduler_enabled=True), follow_redirects=True)
    watch = datastore.data['watching'][uuid]
    assert watch['time_schedule_limit'].enabled is True
    assert _stored_schedule(watch) == {'enabled': True}

    # Turned off again but with a custom day, the custom day is kept
    client.post(url_for("ui.ui_edit.edit_page", uuid=uuid), data=_edit_form(test_url, tuesday_start="09:30"), follow_redirects=True)
    watch = datastore.data['watching'][uuid]
    assert watch['time_schedule_limit'].enabled is False
    assert watch['time_schedule_limit'].tuesday.start_time == "09:30"
    assert _stored_schedule(watch) == {'tuesday': {'start_time': '09:30'}}
    assert watch['time_schedule_limit'].monday is DEFAULT_TIME_SCHEDULE_LIMIT.monday

    delete_all_watches(client)


def test_api_schedule_is_int_and_roundtrips(client, live_server, measure_memory_usage, datastore_path):
    set_original_response(datastore_path=datastore_path)
    test_url = url_for('test_endpoint', _external=True)
    datastore = live_server.app.config['DATASTORE']
    api_key = datastore.data['settings']['application'].get('api_access_token')
    headers = {'x-api-key': api_key, 'content-type': 'application/json'}
    uuid = datastore.add_watch(url=test_url)
    wait_for_all_checks(client)

    res = client.get(url_for("watch", uuid=uuid), headers=headers)
    assert res.status_code == 200
    schedule = res.json['time_schedule_limit']
    assert schedule['monday']['duration'] == {'hours': 24, 'minutes': 0}
    assert 'timezone' not in schedule, "no nulls, a GET must be PUT-able straight back"

    # What came out goes straight back in
    res = client.put(url_for("watch", uuid=uuid), headers=headers, data=json.dumps({'time_schedule_limit': schedule}))
    assert res.status_code == 200, res.data

    # Strings are no longer accepted by the API
    schedule['monday']['duration'] = {'hours': '24', 'minutes': '00'}
    res = client.put(url_for("watch", uuid=uuid), headers=headers, data=json.dumps({'time_schedule_limit': schedule}))
    assert res.status_code == 400
    assert b"is not of type 'integer'" in res.data

    # A partial schedule is fine, the rest are the defaults
    res = client.put(url_for("watch", uuid=uuid), headers=headers,
                     data=json.dumps({'time_schedule_limit': {'enabled': True, 'friday': {'enabled': False}}}))
    assert res.status_code == 200, res.data
    stored = datastore.data['watching'][uuid]['time_schedule_limit']
    assert stored.enabled is True and stored.friday.enabled is False
    assert stored.monday is DEFAULT_TIME_SCHEDULE_LIMIT.monday

    delete_all_watches(client)
