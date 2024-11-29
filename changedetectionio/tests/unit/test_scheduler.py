#!/usr/bin/env python3

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_jinja2_security

import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

class TestScheduler(unittest.TestCase):

    # UTC+14:00 (Line Islands, Kiribati) is the farthest ahead, always ahead of UTC.
    # UTC-12:00 (Baker Island, Howland Island) is the farthest behind, always one calendar day behind UTC.

    def test_timezone_basic_time_within_schedule(self):
        from changedetectionio import time_handler

        timezone_str = 'Europe/Berlin'
        debug_datetime = datetime.now(ZoneInfo(timezone_str))
        day_of_week = debug_datetime.strftime('%A')
        time_str = str(debug_datetime.hour)+':00'
        duration = 60  # minutes

        # The current time should always be within 60 minutes of [time_hour]:00
        result = time_handler.am_i_inside_time(day_of_week=day_of_week,
                                               time_str=time_str,
                                               timezone_str=timezone_str,
                                               duration=duration)

        self.assertEqual(result, True, f"{debug_datetime} is within time scheduler {day_of_week} {time_str} in {timezone_str} for {duration} minutes")

    def test_timezone_basic_time_outside_schedule(self):
        from changedetectionio import time_handler

        timezone_str = 'Europe/Berlin'
        # We try a date in the future..
        debug_datetime = datetime.now(ZoneInfo(timezone_str))+ timedelta(days=-1)
        day_of_week = debug_datetime.strftime('%A')
        time_str = str(debug_datetime.hour) + ':00'
        duration = 60*24  # minutes

        # The current time should always be within 60 minutes of [time_hour]:00
        result = time_handler.am_i_inside_time(day_of_week=day_of_week,
                                               time_str=time_str,
                                               timezone_str=timezone_str,
                                               duration=duration)

        self.assertNotEqual(result, True,
                         f"{debug_datetime} is NOT within time scheduler {day_of_week} {time_str} in {timezone_str} for {duration} minutes")


if __name__ == '__main__':
    unittest.main()
