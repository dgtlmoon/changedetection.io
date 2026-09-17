#!/usr/bin/env python3

"""
Regression tests for two scheduler/timezone bugs.

BUG 1 - edit page returned HTTP 500
  ui/edit.py resolved the default timezone with
      .get('scheduler_timezone_default', os.getenv('TZ', 'UTC'))
  but App.py initialises that key to None, so the key EXISTS and dict.get()
  never uses its fallback. None reached is_within_schedule(), which does
  `tz_name.strip()` -> AttributeError -> the handler did `return False` -> Flask
  raised TypeError ("view function did not return a valid response ... it was a
  bool") -> HTTP 500. The watch was actually saved, so the user saw a 500 on a
  successful save.

BUG 2 - ticker thread died silently
  Same root cause, but flask_app.py's `return False` was inside the ticker
  thread's main loop. One watch with an unresolvable timezone ended the thread
  and NO watch was ever checked again until restart, with the process still up.

Run:  pytest changedetectionio/tests/test_scheduler_timezone_regressions.py
"""

import time

from flask import url_for

from .util import live_server_setup, wait_for_all_checks, set_original_response


DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']


def _schedule_form(url, enabled_days=('monday',)):
    data = {
        "url": url,
        "fetch_backend": "html_requests",
        "time_between_check_use_default": "",
        "time_between_check-seconds": 1,
        "time_schedule_limit-enabled": 'y',
    }
    for day in DAYS:
        data[f"time_schedule_limit-{day}-start_time"] = "00:00"
        data[f"time_schedule_limit-{day}-duration-hours"] = 24
        data[f"time_schedule_limit-{day}-duration-minutes"] = 0
        if day in enabled_days:
            data[f"time_schedule_limit-{day}-enabled"] = 'y'
    return data


def _full_schedule(enabled=True, timezone=None):
    sched = {'enabled': True}
    for day in DAYS:
        sched[day] = {'enabled': enabled, 'start_time': '00:00',
                      'duration': {'hours': '24', 'minutes': '00'}}
    if timezone is not None:
        sched['timezone'] = timezone
    return sched


def test_edit_page_saves_when_no_default_timezone_configured(client, live_server, measure_memory_usage, datastore_path):
    """BUG 1: enabling the scheduler with scheduler_timezone_default unset 500'd."""
    set_original_response(datastore_path=datastore_path)
    test_url = url_for('test_endpoint', _external=True)
    datastore = live_server.app.config['DATASTORE']

    # This is the default state from model/App.py - key present, value None.
    datastore.data['settings']['application']['scheduler_timezone_default'] = None

    uuid = datastore.add_watch(url=test_url)
    wait_for_all_checks(client)

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid),
        data=_schedule_form(test_url),
        follow_redirects=True,
    )

    assert res.status_code == 200, f"expected 200, got {res.status_code}"
    assert b"Internal Server Error" not in res.data
    assert b"Updated watch." in res.data

    # and the schedule really was saved
    assert datastore.data['watching'][uuid]['time_schedule_limit']['enabled'] is True


def test_edit_page_saves_with_unresolvable_timezone(client, live_server, measure_memory_usage, datastore_path):
    """A garbage timezone must degrade to 'skip the recheck', not 500."""
    set_original_response(datastore_path=datastore_path)
    test_url = url_for('test_endpoint', _external=True)
    datastore = live_server.app.config['DATASTORE']
    datastore.data['settings']['application']['scheduler_timezone_default'] = 'Not/ARealZone'

    uuid = datastore.add_watch(url=test_url)
    wait_for_all_checks(client)

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid),
        data=_schedule_form(test_url),
        follow_redirects=True,
    )
    assert res.status_code == 200, f"expected 200, got {res.status_code}"
    assert b"Updated watch." in res.data


def test_ticker_survives_a_watch_with_a_broken_timezone(client, live_server, measure_memory_usage, datastore_path):
    """
    BUG 2: one bad watch used to kill the ticker thread, stopping every other
    watch. Prove a healthy watch still gets checked alongside a broken one.
    """
    set_original_response(datastore_path=datastore_path)
    test_url = url_for('test_endpoint', _external=True)
    datastore = live_server.app.config['DATASTORE']
    datastore.data['settings']['application']['scheduler_timezone_default'] = None

    broken_uuid = datastore.add_watch(url=test_url)
    healthy_uuid = datastore.add_watch(url=test_url)
    wait_for_all_checks(client)

    # Broken watch: scheduler on, timezone that arrow cannot resolve
    datastore.data['watching'][broken_uuid]['time_between_check_use_default'] = False
    datastore.data['watching'][broken_uuid]['time_schedule_limit'] = _full_schedule(
        timezone='Not/ARealZone'
    )

    # Healthy watch: no schedule limit, short interval so the ticker must pick it up
    datastore.data['watching'][healthy_uuid]['time_between_check_use_default'] = False
    datastore.data['watching'][healthy_uuid]['time_between_check'] = {
        'weeks': None, 'days': None, 'hours': None, 'minutes': None, 'seconds': 2
    }
    before = datastore.data['watching'][healthy_uuid]['last_checked']

    # Give the ticker several passes over the broken watch
    deadline = time.time() + 30
    while time.time() < deadline:
        if datastore.data['watching'][healthy_uuid]['last_checked'] != before:
            break
        time.sleep(0.5)

    assert datastore.data['watching'][healthy_uuid]['last_checked'] != before, (
        "the healthy watch was never rechecked - the ticker thread most likely "
        "died on the broken watch's timezone"
    )


def test_api_rejects_invalid_timezone_on_update(client, live_server, measure_memory_usage, datastore_path):
    """
    The edit form runs validateTimeZoneName, but the API did not - the OpenAPI
    schema for time_schedule_limit declares no `timezone` property and does not
    set additionalProperties:false, so any string was accepted and stored.
    A bogus zone makes arrow.now(tz) raise inside the scheduler.
    """
    import json
    set_original_response(datastore_path=datastore_path)
    test_url = url_for('test_endpoint', _external=True)
    datastore = live_server.app.config['DATASTORE']
    api_key = datastore.data['settings']['application'].get('api_access_token')

    uuid = datastore.add_watch(url=test_url)
    wait_for_all_checks(client)

    res = client.put(
        url_for("watch", uuid=uuid),
        headers={'x-api-key': api_key, 'content-type': 'application/json'},
        data=json.dumps({'time_schedule_limit': _full_schedule(timezone='Not/ARealZone')}),
    )
    assert res.status_code == 400, f"expected 400, got {res.status_code}: {res.data}"
    assert b'not a valid timezone' in res.data.lower()

    stored = datastore.data['watching'][uuid]['time_schedule_limit']
    assert stored.get('timezone') != 'Not/ARealZone', "invalid timezone was persisted anyway"


def test_api_accepts_valid_timezone_on_update(client, live_server, measure_memory_usage, datastore_path):
    """The validation must not block legitimate zones."""
    import json
    set_original_response(datastore_path=datastore_path)
    test_url = url_for('test_endpoint', _external=True)
    datastore = live_server.app.config['DATASTORE']
    api_key = datastore.data['settings']['application'].get('api_access_token')

    uuid = datastore.add_watch(url=test_url)
    wait_for_all_checks(client)

    for tz in ('Europe/Berlin', 'UTC', 'Pacific/Kiritimati'):
        res = client.put(
            url_for("watch", uuid=uuid),
            headers={'x-api-key': api_key, 'content-type': 'application/json'},
            data=json.dumps({'time_schedule_limit': _full_schedule(timezone=tz)}),
        )
        assert res.status_code == 200, f"{tz} rejected: {res.data}"
        assert datastore.data['watching'][uuid]['time_schedule_limit']['timezone'] == tz

    # omitting the timezone entirely stays valid
    res = client.put(
        url_for("watch", uuid=uuid),
        headers={'x-api-key': api_key, 'content-type': 'application/json'},
        data=json.dumps({'time_schedule_limit': _full_schedule()}),
    )
    assert res.status_code == 200, res.data


def test_api_rejects_invalid_timezone_on_create(client, live_server, measure_memory_usage, datastore_path):
    """Same guard on POST /watch, otherwise it is just a different door."""
    import json
    set_original_response(datastore_path=datastore_path)
    test_url = url_for('test_endpoint', _external=True)
    datastore = live_server.app.config['DATASTORE']
    api_key = datastore.data['settings']['application'].get('api_access_token')

    res = client.post(
        url_for("createwatch"),
        headers={'x-api-key': api_key, 'content-type': 'application/json'},
        data=json.dumps({'url': test_url,
                         'time_schedule_limit': _full_schedule(timezone='Bogus/Zone')}),
    )
    assert res.status_code == 400, f"expected 400, got {res.status_code}: {res.data}"
    assert b'not a valid timezone' in res.data.lower()


def test_ignore_text_via_selection_marks_watch_edited(client, live_server, measure_memory_usage, datastore_path):
    """
    The selection UI appended to ignore_text in place. That bypasses
    watch_base.__setitem__, so was_edited stayed False and the
    'content unchanged since last check' skip stayed active - the new
    ignore_text would not take effect until the page changed on its own.
    """
    set_original_response(datastore_path=datastore_path)
    test_url = url_for('test_endpoint', _external=True)
    datastore = live_server.app.config['DATASTORE']

    uuid = datastore.add_watch(url=test_url)
    wait_for_all_checks(client)

    watch = datastore.data['watching'][uuid]
    watch.reset_watch_edited_flag()
    assert watch.was_edited is False, "precondition: flag should start clear"

    res = client.post(
        url_for("ui.ui_edit.highlight_submit_ignore_url", uuid=uuid),
        data={'mode': 'exact', 'selection': 'Which is across multiple lines'},
        follow_redirects=True,
    )
    assert res.status_code == 200

    watch = datastore.data['watching'][uuid]
    assert 'Which is across multiple lines' in watch['ignore_text'], "the text was not stored"
    assert watch.was_edited is True, (
        "watch was not flagged as edited - the new ignore_text will not be applied "
        "until the page content changes on its own"
    )


def test_ignore_text_digit_regex_marks_watch_edited(client, live_server, measure_memory_usage, datastore_path):
    """Same for the digit-regex branch."""
    set_original_response(datastore_path=datastore_path)
    test_url = url_for('test_endpoint', _external=True)
    datastore = live_server.app.config['DATASTORE']

    uuid = datastore.add_watch(url=test_url)
    wait_for_all_checks(client)

    datastore.data['watching'][uuid].reset_watch_edited_flag()

    res = client.post(
        url_for("ui.ui_edit.highlight_submit_ignore_url", uuid=uuid),
        data={'mode': 'digit-regex', 'selection': 'Updated 1234 times'},
        follow_redirects=True,
    )
    assert res.status_code == 200

    watch = datastore.data['watching'][uuid]
    assert any(t.startswith('/') and t.endswith('/') for t in watch['ignore_text']), \
        f"expected a regex entry, got {watch['ignore_text']}"
    assert watch.was_edited is True


def test_ignore_text_appends_to_existing(client, live_server, measure_memory_usage, datastore_path):
    """Rebinding must preserve entries already there, not replace them."""
    set_original_response(datastore_path=datastore_path)
    test_url = url_for('test_endpoint', _external=True)
    datastore = live_server.app.config['DATASTORE']

    uuid = datastore.add_watch(url=test_url)
    wait_for_all_checks(client)
    datastore.data['watching'][uuid]['ignore_text'] = ['already here']

    client.post(
        url_for("ui.ui_edit.highlight_submit_ignore_url", uuid=uuid),
        data={'mode': 'exact', 'selection': 'line one\nline two'},
        follow_redirects=True,
    )

    ignore_text = datastore.data['watching'][uuid]['ignore_text']
    assert 'already here' in ignore_text, "existing entries were lost"
    assert 'line one' in ignore_text
    assert 'line two' in ignore_text
