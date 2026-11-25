#!/usr/bin/env python3
"""A group can set the recheck time (interval and time schedule) for its watches. Off by default: a group changes
nothing until it is switched on, then it is either used by the watches left on "Use global settings", or it is
used instead of the watch's own. See model/group_settings.py."""

import time

import pytest
from flask import url_for

from changedetectionio.api.SystemInfo import overdue_watch_uuids
from changedetectionio.model.group_settings import groups_with_recheck_time, recheck_time_group_choice
from .util import set_original_response, wait_for_all_checks, delete_all_watches

DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']


@pytest.fixture
def setup(client, live_server, datastore_path):
    datastore = client.application.config.get('DATASTORE')
    timezone_before = datastore.data['settings']['application'].get('scheduler_timezone_default')
    # The time schedule is only offered once a time zone is set
    datastore.data['settings']['application']['scheduler_timezone_default'] = 'UTC'
    yield datastore
    datastore.data['settings']['application']['scheduler_timezone_default'] = timezone_before
    datastore.data['settings']['application']['tags'].clear()
    delete_all_watches(client)


def _group(datastore, title, **settings):
    uuid = datastore.add_tag(title=title)
    group = datastore.data['settings']['application']['tags'][uuid]
    group.update(settings)
    return uuid, group


def _watch(datastore, tags=(), **settings):
    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True), extras={'paused': True, **settings})
    watch = datastore.data['watching'][uuid]
    watch['tags'] = list(tags)
    return uuid, watch


def _choice(datastore, watch):
    return recheck_time_group_choice(watch, groups_with_recheck_time(datastore))


def _schedule_that_is_never_open():
    return {'enabled': True, **{day: {'enabled': False} for day in DAYS}}


def test_group_recheck_time_does_nothing_until_switched_on(client, live_server, measure_memory_usage, datastore_path, setup):
    datastore = setup

    group_uuid, group = _group(datastore, 'Shops')
    assert group['time_between_check_group_mode'] == 'off'

    # Set up but not switched on, and a group saved before the setting existed, change nothing
    group['time_between_check'] = {'hours': 2}
    _, old_group = _group(datastore, 'From an older version', time_between_check={'hours': 2})
    del old_group['time_between_check_group_mode']

    _, on_default = _watch(datastore, tags=[group_uuid, old_group['uuid']])
    _, own = _watch(datastore, tags=[group_uuid], time_between_check_use_default=False, time_between_check={'minutes': 5})

    assert not groups_with_recheck_time(datastore), "Nothing switched on, so the scheduler has no group to look at"
    assert _choice(datastore, on_default) is None
    assert _choice(datastore, own) is None


def test_group_recheck_time_fallback_and_replace(client, live_server, measure_memory_usage, datastore_path, setup):
    datastore = setup
    group_uuid, group = _group(datastore, 'Shops', time_between_check={'hours': 2},
                               time_between_check_group_mode='fallback')

    _, on_default = _watch(datastore, tags=[group_uuid])
    _, own = _watch(datastore, tags=[group_uuid], time_between_check_use_default=False, time_between_check={'minutes': 5})
    _, not_in_group = _watch(datastore)

    # Fallback: only the watch that was left on "Use global settings"
    choice = _choice(datastore, on_default)
    assert (choice.value, choice.group['uuid'], choice.replaces_watch) == (7200, group_uuid, False)
    assert _choice(datastore, own) is None
    assert _choice(datastore, not_in_group) is None

    # Replace: also the watch that has its own
    group['time_between_check_group_mode'] = 'replace'
    choice = _choice(datastore, own)
    assert (choice.value, choice.replaces_watch) == (7200, True)
    assert _choice(datastore, not_in_group) is None

    # Switched on with nothing set is the same as off
    group['time_between_check'] = {'hours': None, 'minutes': 0}
    assert _choice(datastore, own) is None


def test_group_recheck_time_first_group_wins(client, live_server, measure_memory_usage, datastore_path, setup):
    datastore = setup
    first_uuid, first = _group(datastore, 'First', time_between_check={'hours': 1},
                               time_between_check_group_mode='fallback')
    second_uuid, second = _group(datastore, 'Second', time_between_check={'hours': 6},
                                 time_between_check_group_mode='fallback')
    # Applied by URL pattern, not in the watch's own list, so it comes after those
    by_url_uuid, by_url = _group(datastore, 'By URL', time_between_check={'days': 1},
                                 time_between_check_group_mode='fallback', url_match_pattern='*/test-endpoint*')

    _, watch = _watch(datastore, tags=[second_uuid, first_uuid])
    assert _choice(datastore, watch).group['uuid'] == second_uuid, "The order of the watch's own group list"

    _, only_by_url = _watch(datastore)
    assert _choice(datastore, only_by_url).value == 86400

    # A group that replaces goes before one that is only a fallback
    first['time_between_check_group_mode'] = 'replace'
    choice = _choice(datastore, watch)
    assert (choice.group['uuid'], choice.replaces_watch) == (first_uuid, True)

    # A group that is switched off is passed over
    first['time_between_check_group_mode'] = 'off'
    second['time_between_check_group_mode'] = 'off'
    assert _choice(datastore, watch).group['uuid'] == by_url_uuid


def test_group_with_only_a_schedule_keeps_the_system_interval(client, live_server, measure_memory_usage, datastore_path, setup):
    datastore = setup
    group_uuid, group = _group(datastore, 'Business hours', time_schedule_limit=_schedule_that_is_never_open(),
                               time_between_check_group_mode='replace')
    _, watch = _watch(datastore, tags=[group_uuid])

    choice = _choice(datastore, watch)
    assert choice.group['uuid'] == group_uuid
    assert choice.value == 0, "No interval of its own, the scheduler uses the system default"


def test_overdue_follows_the_group_interval(client, live_server, measure_memory_usage, datastore_path, setup):
    datastore = setup
    group_uuid, group = _group(datastore, 'Weekly', time_between_check={'weeks': 1})
    uuid, watch = _watch(datastore, tags=[group_uuid], time_between_check_use_default=False,
                         time_between_check={'minutes': 5})
    watch['paused'] = False
    watch['last_checked'] = int(time.time()) - 3600

    assert uuid in overdue_watch_uuids(datastore), "An hour late for its own 5 minutes"
    group['time_between_check_group_mode'] = 'replace'
    assert uuid not in overdue_watch_uuids(datastore), "The group says weekly"


def test_scheduler_uses_the_group_recheck_time(client, live_server, measure_memory_usage, datastore_path, setup):
    datastore = setup
    set_original_response(datastore_path=datastore_path)

    # On its own the watch would not be checked again for weeks
    group_uuid, group = _group(datastore, 'Often', time_between_check={'seconds': 1})
    uuid, watch = _watch(datastore, tags=[group_uuid], time_between_check_use_default=False,
                         time_between_check={'weeks': 4})
    watch['paused'] = False
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    last_checked = watch['last_checked']
    assert last_checked

    # Past MINIMUM_SECONDS_RECHECK_TIME, the scheduler still leaves it alone
    time.sleep(5)
    wait_for_all_checks(client)
    assert watch['last_checked'] == last_checked, "Group is not switched on, the watch keeps its own 4 weeks"

    group['time_between_check_group_mode'] = 'replace'
    for _ in range(20):
        time.sleep(1)
        if watch['last_checked'] != last_checked:
            break
    wait_for_all_checks(client)
    assert watch['last_checked'] != last_checked, "The group's 1 second is used instead of the watch's 4 weeks"

    # The group's time schedule goes with it: one that is never open stops the checks
    group['time_schedule_limit'] = _schedule_that_is_never_open()
    wait_for_all_checks(client)
    time.sleep(2)
    wait_for_all_checks(client)
    last_checked = watch['last_checked']
    time.sleep(6)
    assert watch['last_checked'] == last_checked, "Outside the group's schedule"


def test_group_recheck_time_tab_and_watch_edit_note(client, live_server, measure_memory_usage, datastore_path, setup):
    datastore = setup
    group_uuid, group = _group(datastore, 'Shops <b>&</b> more')
    uuid, watch = _watch(datastore, tags=[group_uuid])

    res = client.get(url_for("tags.form_tag_edit", uuid=group_uuid))
    assert b'href="#recheck-time"' in res.data
    assert b'name="time_between_check_group_mode"' in res.data
    assert b'name="time_between_check-hours"' in res.data
    assert b'id="time_schedule_limit-enabled"' in res.data
    assert b'border-fieldset group-setting-off' in res.data, "Dimmed while the mode is off"

    res = client.get(url_for("ui.ui_edit.edit_page", uuid=uuid))
    assert b'decided-elsewhere-note' not in res.data

    res = client.post(
        url_for("tags.form_tag_edit_submit", uuid=group_uuid),
        data={"title": group['title'], "time_between_check_group_mode": "replace",
              "time_between_check-hours": 2, "time_between_check-minutes": 30},
        follow_redirects=True,
    )
    assert b"Updated" in res.data
    assert group['time_between_check_group_mode'] == 'replace'
    assert (group['time_between_check']['hours'], group['time_between_check']['minutes']) == (2, 30)
    res = client.get(url_for("tags.form_tag_edit", uuid=group_uuid))
    assert b'group-setting-off" data-dimmed-while-off="time_between_check_group_mode"' not in res.data, "Not dimmed once it is switched on"

    res = client.get(url_for("ui.ui_edit.edit_page", uuid=uuid))
    group_link = url_for('tags.form_tag_edit', uuid=group_uuid).encode()
    assert b'Decided by group <a href="' + group_link + b'#recheck-time"' in res.data, "Names the group, with a link to its tab"
    assert b'2 hours, 30 minutes' in res.data
    assert b'Shops &lt;b&gt;&amp;&lt;/b&gt; more' in res.data and b'Shops <b>' not in res.data, "The group title is escaped"
    assert b'time-between-check border-fieldset decided-elsewhere' in res.data, "The watch's own is shown as having no effect"

    # Saving the watch keeps the watch's own settings, the group is not written into it
    client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid),
        data={"url": watch['url'], "tags": "", "fetch_backend": "html_requests", "time_between_check_use_default": "y"},
        follow_redirects=True,
    )
    watch = datastore.data['watching'][uuid]
    assert watch['time_between_check_use_default'] is True
    assert not any((watch.get('time_between_check') or {}).values())
    # That form also cleared the watch's groups
    watch['tags'] = [group_uuid]

    # As a fallback it says so, and the watch's controls stay usable
    group['time_between_check_group_mode'] = 'fallback'
    res = client.get(url_for("ui.ui_edit.edit_page", uuid=uuid))
    assert b'From group <a href="' + group_link + b'#recheck-time"' in res.data
    assert b'time-between-check border-fieldset decided-elsewhere' not in res.data

    # Posting the group form without the tab's fields (as older clients do) leaves the mode alone
    client.post(url_for("tags.form_tag_edit_submit", uuid=group_uuid), data={"title": group['title']}, follow_redirects=True)
    assert group['time_between_check_group_mode'] == 'fallback'
