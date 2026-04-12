#!/usr/bin/env python3

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_scheduler

import unittest
import arrow

class TestScheduler(unittest.TestCase):

    # UTC+14:00 (Line Islands, Kiribati) is the farthest ahead, always ahead of UTC.
    # UTC-12:00 (Baker Island, Howland Island) is the farthest behind, always one calendar day behind UTC.

    def test_timezone_basic_time_within_schedule(self):
        """Test that current time is detected as within schedule window."""
        from changedetectionio import time_handler

        timezone_str = 'Europe/Berlin'
        debug_datetime = arrow.now(timezone_str)
        day_of_week = debug_datetime.format('dddd')
        time_str = debug_datetime.format('HH:00')
        duration = 60  # minutes

        # The current time should always be within 60 minutes of [time_hour]:00
        result = time_handler.am_i_inside_time(day_of_week=day_of_week,
                                               time_str=time_str,
                                               timezone_str=timezone_str,
                                               duration=duration)

        self.assertEqual(result, True, f"{debug_datetime} is within time scheduler {day_of_week} {time_str} in {timezone_str} for {duration} minutes")

    def test_timezone_basic_time_outside_schedule(self):
        """Test that time from yesterday is outside current schedule."""
        from changedetectionio import time_handler

        timezone_str = 'Europe/Berlin'
        # We try a date in the past (yesterday)
        debug_datetime = arrow.now(timezone_str).shift(days=-1)
        day_of_week = debug_datetime.format('dddd')
        time_str = debug_datetime.format('HH:00')
        duration = 60 * 24  # minutes

        # The current time should NOT be within yesterday's schedule
        result = time_handler.am_i_inside_time(day_of_week=day_of_week,
                                               time_str=time_str,
                                               timezone_str=timezone_str,
                                               duration=duration)

        self.assertNotEqual(result, True,
                         f"{debug_datetime} is NOT within time scheduler {day_of_week} {time_str} in {timezone_str} for {duration} minutes")

    def test_timezone_utc_within_schedule(self):
        """Test UTC timezone works correctly."""
        from changedetectionio import time_handler

        timezone_str = 'UTC'
        debug_datetime = arrow.now(timezone_str)
        day_of_week = debug_datetime.format('dddd')
        time_str = debug_datetime.format('HH:00')
        duration = 120  # minutes

        result = time_handler.am_i_inside_time(day_of_week=day_of_week,
                                               time_str=time_str,
                                               timezone_str=timezone_str,
                                               duration=duration)

        self.assertTrue(result, "Current time should be within UTC schedule")

    def test_timezone_extreme_ahead(self):
        """Test with UTC+14 timezone (Line Islands, Kiribati)."""
        from changedetectionio import time_handler

        timezone_str = 'Pacific/Kiritimati'  # UTC+14
        debug_datetime = arrow.now(timezone_str)
        day_of_week = debug_datetime.format('dddd')
        time_str = debug_datetime.format('HH:00')
        duration = 60

        result = time_handler.am_i_inside_time(day_of_week=day_of_week,
                                               time_str=time_str,
                                               timezone_str=timezone_str,
                                               duration=duration)

        self.assertTrue(result, "Should work with extreme ahead timezone")

    def test_timezone_extreme_behind(self):
        """Test with UTC-12 timezone (Baker Island)."""
        from changedetectionio import time_handler

        # Using Etc/GMT+12 which is UTC-12 (confusing, but that's how it works)
        timezone_str = 'Etc/GMT+12'  # UTC-12
        debug_datetime = arrow.now(timezone_str)
        day_of_week = debug_datetime.format('dddd')
        time_str = debug_datetime.format('HH:00')
        duration = 60

        result = time_handler.am_i_inside_time(day_of_week=day_of_week,
                                               time_str=time_str,
                                               timezone_str=timezone_str,
                                               duration=duration)

        self.assertTrue(result, "Should work with extreme behind timezone")


if __name__ == '__main__':
    unittest.main()
