#!/usr/bin/env python3

# run from dir above changedetectionio/ dir
# python3 -m pytest changedetectionio/tests/unit/test_frozen_shared_values.py -v

import json
import pickle
import unittest
from copy import deepcopy

import orjson

from changedetectionio.model import Watch, Tag
from changedetectionio.model.frozen import FrozenDict, intern_frozen, thaw
from changedetectionio import time_handler


def _new_watch(**data):
    mock_datastore = {'settings': {'application': {}}, 'watching': {}}
    return Watch.model(datastore_path='/tmp', __datastore=mock_datastore, default=data)


def _custom_schedule():
    schedule = json.loads(json.dumps(_new_watch()['time_schedule_limit']))
    schedule['enabled'] = True
    schedule['timezone'] = 'Europe/Berlin'
    schedule['monday']['start_time'] = '09:30'
    return schedule


class TestFrozenSharedValues(unittest.TestCase):

    def test_default_schedule_is_one_shared_object(self):
        a, b = _new_watch(), _new_watch()
        self.assertIs(a['time_schedule_limit'], b['time_schedule_limit'])
        self.assertIsInstance(a['time_schedule_limit'], FrozenDict)

    def test_loaded_identical_schedules_are_shared(self):
        # The rehydrate path passes the parsed watch.json as default=
        a = _new_watch(time_schedule_limit=_custom_schedule())
        b = _new_watch(time_schedule_limit=_custom_schedule())
        self.assertIs(a['time_schedule_limit'], b['time_schedule_limit'])
        self.assertIsNot(a['time_schedule_limit'], _new_watch()['time_schedule_limit'])

    def test_in_place_writes_raise_and_never_reach_other_watches(self):
        a, b = _new_watch(), _new_watch()
        schedule = a['time_schedule_limit']
        writes = [
            lambda: schedule.__setitem__('enabled', True),
            lambda: schedule['monday'].__setitem__('enabled', False),
            lambda: schedule['monday']['duration'].__setitem__('hours', '1'),
            lambda: schedule.update({'enabled': True}),
            lambda: schedule.setdefault('timezone', 'UTC'),
            lambda: schedule.pop('enabled'),
            lambda: schedule.popitem(),
            lambda: schedule.clear(),
            lambda: schedule.__delitem__('enabled'),
            lambda: schedule.__ior__({'enabled': True}),
        ]
        for write in writes:
            with self.assertRaises(TypeError):
                write()
        self.assertFalse(b['time_schedule_limit']['enabled'])
        self.assertTrue(b['time_schedule_limit']['monday']['enabled'])
        self.assertEqual(b['time_schedule_limit']['monday']['duration']['hours'], '24')

    def test_assigning_a_new_value_only_changes_that_watch(self):
        a, b = _new_watch(), _new_watch()
        a['time_schedule_limit'] = _custom_schedule()
        self.assertTrue(a['time_schedule_limit']['enabled'])
        self.assertIsInstance(a['time_schedule_limit'], FrozenDict)
        self.assertTrue(a.was_edited)
        self.assertFalse(b['time_schedule_limit']['enabled'])

    def test_update_from_form_or_api_is_interned(self):
        a, b = _new_watch(), _new_watch()
        a.update({'time_schedule_limit': _custom_schedule()})
        b.update(time_schedule_limit=_custom_schedule())
        self.assertIsInstance(a['time_schedule_limit'], FrozenDict)
        self.assertIs(a['time_schedule_limit'], b['time_schedule_limit'])

    def test_serialises_byte_identical_to_the_plain_dict(self):
        plain = _custom_schedule()
        watch = _new_watch(time_schedule_limit=_custom_schedule())
        self.assertEqual(orjson.dumps(watch['time_schedule_limit']), orjson.dumps(plain))
        self.assertEqual(json.dumps(watch['time_schedule_limit']), json.dumps(plain))
        self.assertEqual(watch['time_schedule_limit'], plain)
        self.assertIsInstance(watch['time_schedule_limit'], dict)
        # What commit() writes, and the share feature's json.dumps(watch)
        self.assertEqual(watch._get_commit_data()['time_schedule_limit'], plain)
        json.dumps(dict(watch))

    def test_key_order_and_types_are_part_of_identity(self):
        a = intern_frozen({'enabled': True, 'x': 1})
        self.assertIsNot(a, intern_frozen({'x': 1, 'enabled': True}))
        self.assertIsNot(a, intern_frozen({'enabled': 1, 'x': 1}))
        self.assertIs(a, intern_frozen({'enabled': True, 'x': 1}))

    def test_non_dict_values_pass_through_unchanged(self):
        for value in (None, '', [], 'garbage', 0):
            self.assertIs(intern_frozen(value), value)
        watch = _new_watch(time_schedule_limit=None)
        self.assertIsNone(watch['time_schedule_limit'])

    def test_deepcopy_clone_and_pickle_keep_the_shared_object(self):
        watch = _new_watch()
        shared = watch['time_schedule_limit']
        self.assertIs(deepcopy(watch)['time_schedule_limit'], shared)
        restored = pickle.loads(pickle.dumps(shared))
        self.assertEqual(restored, shared)
        self.assertIsInstance(restored, FrozenDict)

    def test_thaw_gives_a_writable_copy_to_assign_back(self):
        a, b = _new_watch(), _new_watch()
        schedule = thaw(a['time_schedule_limit'])
        self.assertIs(type(schedule['monday']['duration']), dict)
        schedule['monday']['enabled'] = False
        a['time_schedule_limit'] = schedule
        self.assertFalse(a['time_schedule_limit']['monday']['enabled'])
        self.assertTrue(b['time_schedule_limit']['monday']['enabled'])

    def test_tags_share_it_too(self):
        tag = Tag.model(datastore_path='/tmp', __datastore={'settings': {'application': {}}}, default={})
        self.assertIs(tag['time_schedule_limit'], _new_watch()['time_schedule_limit'])

    def test_is_within_schedule_reads_frozen_schedule(self):
        disabled = _new_watch()['time_schedule_limit']
        self.assertFalse(time_handler.is_within_schedule(time_schedule_limit=disabled))

        always = json.loads(json.dumps(disabled))
        always['enabled'] = True
        watch = _new_watch(time_schedule_limit=always)
        self.assertTrue(time_handler.is_within_schedule(time_schedule_limit=watch['time_schedule_limit']))


if __name__ == '__main__':
    unittest.main()
