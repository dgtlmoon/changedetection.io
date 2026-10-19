#!/usr/bin/env python3
"""
time_schedule_limit as a typed, frozen model (model/TimeScheduleLimit.py, model/shared_defaults.py)

Anything equal to the default is the one shared default instance (memory), and only what
differs from the default is written to watch.json (disk).
"""
import copy
import dataclasses
import json
import os
import pickle
import tempfile
import unittest

from changedetectionio.model import Watch
from changedetectionio.model.TimeScheduleLimit import (
    DAYS_OF_WEEK,
    DEFAULT_TIME_SCHEDULE_LIMIT,
    TimeScheduleLimit,
    as_time_schedule_limit,
)


def legacy_full_week(enabled=False, **day_overrides):
    """The shape every watch.json carried before, strings and all"""
    week = {"enabled": enabled}
    for day in DAYS_OF_WEEK:
        week[day] = {"enabled": True, "start_time": "00:00", "duration": {"hours": "24", "minutes": "00"}}
    week.update(day_overrides)
    return week


def make_watch(datastore_path, **fields):
    datastore = {'settings': {'application': {}, 'requests': {}}, 'watching': {}}
    watch = Watch.model(datastore_path=datastore_path, __datastore=datastore, default=fields)
    watch.ensure_data_dir_exists()
    return watch


class TestSharedDefaults(unittest.TestCase):

    def test_legacy_default_week_becomes_the_shared_default(self):
        self.assertIs(as_time_schedule_limit(legacy_full_week()), DEFAULT_TIME_SCHEDULE_LIMIT)

    def test_empty_values_are_the_default(self):
        for value in (None, {}, ''):
            self.assertIs(as_time_schedule_limit(value), DEFAULT_TIME_SCHEDULE_LIMIT)

    def test_untouched_days_are_shared_across_schedules(self):
        a = as_time_schedule_limit(legacy_full_week(enabled=True))
        b = as_time_schedule_limit(legacy_full_week(tuesday={"enabled": False}))
        self.assertIs(a.monday, b.monday)
        self.assertIs(a.monday, DEFAULT_TIME_SCHEDULE_LIMIT.monday)
        self.assertIs(b.tuesday.duration, DEFAULT_TIME_SCHEDULE_LIMIT.monday.duration)

    def test_blank_timezone_from_the_form_is_not_a_change(self):
        self.assertIs(as_time_schedule_limit({**legacy_full_week(), 'timezone': '  '}), DEFAULT_TIME_SCHEDULE_LIMIT)

    def test_strings_coerce_to_int(self):
        schedule = as_time_schedule_limit(legacy_full_week(enabled=True))
        self.assertEqual(schedule.monday.duration.hours, 24)
        self.assertEqual(schedule.monday.duration.minutes, 0)

    def test_multi_day_duration_is_allowed(self):
        schedule = as_time_schedule_limit({'enabled': True, 'monday': {'duration': {'hours': 48}}})
        self.assertEqual(schedule.monday.duration.hours, 48)

    def test_invalid_stored_value_falls_back_to_default(self):
        """A broken watch.json must not stop the watch loading"""
        self.assertIs(as_time_schedule_limit({'monday': {'duration': {'hours': 'x'}}}), DEFAULT_TIME_SCHEDULE_LIMIT)

    def test_blank_fields_fall_back_per_field_not_per_schedule(self):
        """One empty field in an old watch.json must not throw away the rest of the week"""
        schedule = as_time_schedule_limit(legacy_full_week(
            enabled=True,
            tuesday={"enabled": False, "start_time": "09:00", "duration": {"hours": None, "minutes": ""}},
            wednesday=None,
        ))
        self.assertTrue(schedule.enabled)
        self.assertFalse(schedule.tuesday.enabled)
        self.assertEqual(schedule.tuesday.start_time, "09:00")
        self.assertIs(schedule.tuesday.duration, DEFAULT_TIME_SCHEDULE_LIMIT.monday.duration)
        self.assertIs(schedule.wednesday, DEFAULT_TIME_SCHEDULE_LIMIT.wednesday)

    def test_unparseable_value_logs_the_owner_uuid(self):
        from loguru import logger
        messages = []
        sink = logger.add(lambda m: messages.append(str(m)), level="ERROR")
        try:
            watch = make_watch(tempfile.mkdtemp(), uuid='f00dcafe-0000-4000-8000-000000000001',
                               time_schedule_limit={'monday': {'duration': {'hours': 'x'}}})
        finally:
            logger.remove(sink)
        self.assertIs(watch['time_schedule_limit'], DEFAULT_TIME_SCHEDULE_LIMIT)
        self.assertTrue(any('f00dcafe-0000-4000-8000-000000000001' in m for m in messages), messages)

    def test_frozen_copy_and_pickle(self):
        schedule = as_time_schedule_limit(legacy_full_week(enabled=True))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            schedule.enabled = False
        self.assertIs(copy.deepcopy(schedule), schedule)
        self.assertEqual(pickle.loads(pickle.dumps(schedule)), schedule)
        self.assertFalse(hasattr(schedule, '__dict__'), "slots only, no per-instance dict")


class TestStorageShape(unittest.TestCase):

    def test_default_stores_nothing(self):
        self.assertEqual(DEFAULT_TIME_SCHEDULE_LIMIT.to_storage(), {})

    def test_enabled_with_default_days_keeps_enabled(self):
        """The user ticked 'use time scheduler', that is their setting even if the days are untouched"""
        schedule = as_time_schedule_limit(legacy_full_week(enabled=True))
        self.assertIsNot(schedule, DEFAULT_TIME_SCHEDULE_LIMIT)
        self.assertEqual(schedule.to_storage(), {'enabled': True})

    def test_disabled_custom_schedule_is_kept(self):
        """Turning the scheduler off must not lose the week they set up"""
        custom = {"enabled": True, "start_time": "09:30", "duration": {"hours": "8", "minutes": "15"}}
        schedule = as_time_schedule_limit(legacy_full_week(enabled=False, tuesday=custom))
        self.assertEqual(schedule.to_storage(),
                         {'tuesday': {'start_time': '09:30', 'duration': {'hours': 8, 'minutes': 15}}})
        self.assertEqual(as_time_schedule_limit(schedule.to_storage()), schedule)

    def test_api_shape_is_full_and_has_no_nulls(self):
        """A GET must be PUT-able straight back, the spec does not allow timezone: null"""
        api = DEFAULT_TIME_SCHEDULE_LIMIT.to_api()
        self.assertNotIn('timezone', api)
        self.assertEqual(api['monday'], {'enabled': True, 'start_time': '00:00', 'duration': {'hours': 24, 'minutes': 0}})
        self.assertEqual(set(DAYS_OF_WEEK) | {'enabled'}, set(api.keys()))


class TestWatchIntegration(unittest.TestCase):

    def setUp(self):
        self.datastore_path = tempfile.mkdtemp()

    def test_new_watch_holds_the_shared_default(self):
        self.assertIs(make_watch(self.datastore_path)['time_schedule_limit'], DEFAULT_TIME_SCHEDULE_LIMIT)

    def test_loading_legacy_watch_json_shares_the_default(self):
        watch = make_watch(self.datastore_path, time_schedule_limit=legacy_full_week())
        self.assertIs(watch['time_schedule_limit'], DEFAULT_TIME_SCHEDULE_LIMIT)

    def test_every_write_path_converts(self):
        watch = make_watch(self.datastore_path)
        watch['time_schedule_limit'] = legacy_full_week(enabled=True)
        self.assertIsInstance(watch['time_schedule_limit'], TimeScheduleLimit)

        form_data = {'time_schedule_limit': legacy_full_week()}
        watch.update(form_data)
        self.assertIs(watch['time_schedule_limit'], DEFAULT_TIME_SCHEDULE_LIMIT)
        self.assertIsInstance(form_data['time_schedule_limit'], dict, "the caller's dict must not be mutated")

    def test_commit_writes_only_the_difference(self):
        watch = make_watch(self.datastore_path, time_schedule_limit=legacy_full_week())
        self.assertEqual(watch._get_commit_data()['time_schedule_limit'], {})

        watch['time_schedule_limit'] = legacy_full_week(enabled=True)
        watch.commit()
        with open(os.path.join(watch.data_dir, 'watch.json')) as f:
            self.assertEqual(json.load(f)['time_schedule_limit'], {'enabled': True})

    def test_deepcopy_of_watch_shares_the_schedule(self):
        """Watches are deepcopied on every check, the frozen schedule needs no copy"""
        watch = make_watch(self.datastore_path, time_schedule_limit=legacy_full_week(enabled=True))
        self.assertIs(copy.deepcopy(watch)['time_schedule_limit'], watch['time_schedule_limit'])


class TestUpdate34(unittest.TestCase):

    def test_compacts_watch_json_and_global_ints(self):
        from changedetectionio.store.updates import DatastoreUpdatesMixin

        datastore_path = tempfile.mkdtemp()
        data = {'settings': {'application': {'tags': {}},
                             'requests': {'time_schedule_limit': legacy_full_week()}},
                'watching': {}}
        watch = Watch.model(datastore_path=datastore_path, __datastore=data,
                            default={'time_schedule_limit': legacy_full_week()})
        watch.ensure_data_dir_exists()
        data['watching'][watch['uuid']] = watch

        updater = type('Updater', (DatastoreUpdatesMixin,), {'data': data})()
        updater.update_34()

        with open(os.path.join(watch.data_dir, 'watch.json')) as f:
            self.assertEqual(json.load(f)['time_schedule_limit'], {})
        self.assertEqual(data['settings']['requests']['time_schedule_limit']['monday']['duration'],
                         {'hours': 24, 'minutes': 0})

    def test_partly_blank_schedule_keeps_its_valid_parts_on_disk(self):
        """update_34 commits every watch, a blank field must not wipe the user's week from watch.json"""
        from changedetectionio.store.updates import DatastoreUpdatesMixin

        datastore_path = tempfile.mkdtemp()
        data = {'settings': {'application': {'tags': {}}, 'requests': {}}, 'watching': {}}
        stored = legacy_full_week(enabled=True, friday={"enabled": False, "start_time": "", "duration": {"hours": "", "minutes": None}})
        watch = Watch.model(datastore_path=datastore_path, __datastore=data, default={'time_schedule_limit': stored})
        watch.ensure_data_dir_exists()
        data['watching'][watch['uuid']] = watch

        type('Updater', (DatastoreUpdatesMixin,), {'data': data})().update_34()

        with open(os.path.join(watch.data_dir, 'watch.json')) as f:
            self.assertEqual(json.load(f)['time_schedule_limit'], {'enabled': True, 'friday': {'enabled': False}})


if __name__ == '__main__':
    unittest.main()
