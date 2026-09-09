#!/usr/bin/env python3

"""
Regression tests for the scheduler's default-timezone resolution.

The bug: model/App.py initialises 'scheduler_timezone_default' to None, so the
key ALWAYS EXISTS with a None value. Call sites used

    settings['application'].get('scheduler_timezone_default', os.getenv('TZ', 'UTC'))

which never reaches its fallback, because dict.get() only substitutes the
default when the key is ABSENT - not when its value is None. The resulting None
flowed into is_within_schedule(), which does `tz_name.strip()` and raised
AttributeError. That took out the edit page (HTTP 500) and, worse, the ticker
thread (which did `return False` inside its main loop and stopped scheduling
every watch until restart).

Run:  python3 -m unittest changedetectionio.tests.unit.test_scheduler_timezone_resolution
"""

import os
import unittest
from unittest.mock import patch

from changedetectionio.time_handler import default_timezone_name, is_within_schedule


class TestDefaultTimezoneName(unittest.TestCase):

    def test_none_falls_back_to_utc(self):
        """The exact bug: a present-but-None setting must not stay None."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('TZ', None)
            self.assertEqual(default_timezone_name(None), 'UTC')

    def test_empty_string_falls_back(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('TZ', None)
            self.assertEqual(default_timezone_name(''), 'UTC')
            self.assertEqual(default_timezone_name('   '), 'UTC')

    def test_configured_value_wins(self):
        self.assertEqual(default_timezone_name('Pacific/Kiritimati'), 'Pacific/Kiritimati')

    def test_configured_value_is_stripped(self):
        self.assertEqual(default_timezone_name('  Europe/Berlin  '), 'Europe/Berlin')

    def test_tz_env_used_when_unconfigured(self):
        with patch.dict(os.environ, {'TZ': 'Asia/Tokyo'}):
            self.assertEqual(default_timezone_name(None), 'Asia/Tokyo')

    def test_configured_beats_tz_env(self):
        with patch.dict(os.environ, {'TZ': 'Asia/Tokyo'}):
            self.assertEqual(default_timezone_name('Europe/Berlin'), 'Europe/Berlin')

    def test_never_returns_falsy(self):
        with patch.dict(os.environ, {'TZ': '   '}):
            self.assertEqual(default_timezone_name(None), 'UTC')
        for value in (None, '', '  ', 0, False, []):
            self.assertTrue(default_timezone_name(value),
                            f"default_timezone_name({value!r}) must never be falsy")

    def test_reproduces_the_original_crash(self):
        """Passing the un-resolved None straight through still raises - proving
        the resolver is what prevents it, not luck elsewhere."""
        schedule = {
            'enabled': True,
            'monday': {'enabled': True, 'start_time': '00:00',
                       'duration': {'hours': '24', 'minutes': '00'}},
        }
        with self.assertRaises(AttributeError):
            is_within_schedule(time_schedule_limit=schedule, default_tz=None)

        # ...and does not raise once resolved
        full = {'enabled': True}
        for day in ('monday', 'tuesday', 'wednesday', 'thursday',
                    'friday', 'saturday', 'sunday'):
            full[day] = {'enabled': True, 'start_time': '00:00',
                         'duration': {'hours': '24', 'minutes': '00'}}
        self.assertTrue(
            is_within_schedule(time_schedule_limit=full,
                               default_tz=default_timezone_name(None))
        )


class TestApiTimezoneValidation(unittest.TestCase):
    """
    The edit form runs validateTimeZoneName on time_schedule_limit.timezone, but
    the API did not: the OpenAPI schema declared no `timezone` property and did
    not set additionalProperties:false, so any string was accepted and stored.
    """

    DAYS = ('monday', 'tuesday', 'wednesday', 'thursday',
            'friday', 'saturday', 'sunday')

    def _payload(self, timezone=..., ):
        sched = {'enabled': True}
        for day in self.DAYS:
            sched[day] = {'enabled': True, 'start_time': '00:00',
                          'duration': {'hours': '24', 'minutes': '00'}}
        if timezone is not ...:
            sched['timezone'] = timezone
        return {'time_schedule_limit': sched}

    def setUp(self):
        from changedetectionio.api.Watch import validate_time_schedule_limit
        self.validate = validate_time_schedule_limit

    def test_valid_zones_accepted(self):
        for tz in ('UTC', 'Europe/Berlin', 'America/Los_Angeles', 'Pacific/Kiritimati'):
            self.assertIsNone(self.validate(self._payload(tz)), f"{tz} should be valid")

    def test_absent_or_empty_timezone_is_fine(self):
        self.assertIsNone(self.validate(self._payload()))          # key absent
        self.assertIsNone(self.validate(self._payload('')))        # empty
        self.assertIsNone(self.validate(self._payload(None)))      # explicit null

    def test_unknown_zone_rejected(self):
        err = self.validate(self._payload('Not/ARealZone'))
        self.assertIsNotNone(err)
        self.assertIn('Not/ARealZone', err)
        self.assertIn('not a valid timezone', err.lower())

    def test_case_sensitive_like_the_form(self):
        """'utc' is not an IANA name; the form rejects it, so must the API."""
        self.assertIsNotNone(self.validate(self._payload('utc')))

    def test_non_string_rejected(self):
        for bad in (123, 12.5, True, ['UTC'], {'name': 'UTC'}):
            self.assertIsNotNone(self.validate(self._payload(bad)),
                                 f"{bad!r} should be rejected")

    def test_no_schedule_key_at_all(self):
        self.assertIsNone(self.validate({}))
        self.assertIsNone(self.validate({'time_schedule_limit': None}))
        self.assertIsNone(self.validate({'url': 'https://example.com'}))

    def test_non_dict_schedule_is_left_to_openapi(self):
        """Structural type errors are the OpenAPI layer's job, not ours."""
        self.assertIsNone(self.validate({'time_schedule_limit': 'nope'}))
        self.assertIsNone(self.validate({'time_schedule_limit': []}))

    def test_rejected_zone_would_have_crashed_the_scheduler(self):
        """Tie the validation back to the actual failure it prevents."""
        payload = self._payload('Not/ARealZone')
        self.assertIsNotNone(self.validate(payload))
        with self.assertRaises(Exception):
            is_within_schedule(time_schedule_limit=payload['time_schedule_limit'],
                               default_tz='UTC')


class TestApiSpecDocumentsTimezone(unittest.TestCase):
    """The field is real and settable; the published contract must say so."""

    def test_timezone_is_declared_in_the_openapi_spec(self):
        import os
        import yaml

        here = os.path.dirname(__file__)
        spec_path = os.path.join(here, '..', '..', '..', 'docs', 'api-spec.yaml')
        if not os.path.isfile(spec_path):
            self.skipTest("api-spec.yaml not present in this layout")

        with open(spec_path) as f:
            spec = yaml.safe_load(f)

        schedule = spec['components']['schemas']['WatchBase']['properties']['time_schedule_limit']
        self.assertIn('timezone', schedule['properties'],
                      "time_schedule_limit.timezone is settable via the form and the "
                      "API but is missing from the OpenAPI spec")
        self.assertEqual(schedule['properties']['timezone']['type'], 'string')


if __name__ == '__main__':
    unittest.main()
