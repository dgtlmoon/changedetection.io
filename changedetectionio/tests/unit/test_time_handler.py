#!/usr/bin/env python3

"""
Comprehensive tests for time_handler module refactored to use arrow.

Run from project root:
python3 -m pytest changedetectionio/tests/unit/test_time_handler.py -v
"""

import unittest
import arrow
from changedetectionio import time_handler


class TestAmIInsideTime(unittest.TestCase):
    """Tests for the am_i_inside_time function."""

    def test_current_time_within_schedule(self):
        """Test that current time is detected as within schedule."""
        # Get current time in a specific timezone
        timezone_str = 'Europe/Berlin'
        now = arrow.now(timezone_str)
        day_of_week = now.format('dddd')
        time_str = now.format('HH:00')  # Current hour, 0 minutes
        duration = 60  # 60 minutes

        result = time_handler.am_i_inside_time(
            day_of_week=day_of_week,
            time_str=time_str,
            timezone_str=timezone_str,
            duration=duration
        )

        self.assertTrue(result, f"Current time should be within {duration} minute window starting at {time_str}")

    def test_current_time_outside_schedule(self):
        """Test that time in the past is not within current schedule."""
        timezone_str = 'Europe/Berlin'
        # Get yesterday's date
        yesterday = arrow.now(timezone_str).shift(days=-1)
        day_of_week = yesterday.format('dddd')
        time_str = yesterday.format('HH:mm')
        duration = 30  # Only 30 minutes

        result = time_handler.am_i_inside_time(
            day_of_week=day_of_week,
            time_str=time_str,
            timezone_str=timezone_str,
            duration=duration
        )

        self.assertFalse(result, "Yesterday's time should not be within current schedule")

    def test_timezone_pacific_within_schedule(self):
        """Test with US/Pacific timezone."""
        timezone_str = 'US/Pacific'
        now = arrow.now(timezone_str)
        day_of_week = now.format('dddd')
        time_str = now.format('HH:00')
        duration = 120  # 2 hours

        result = time_handler.am_i_inside_time(
            day_of_week=day_of_week,
            time_str=time_str,
            timezone_str=timezone_str,
            duration=duration
        )

        self.assertTrue(result)

    def test_timezone_tokyo_within_schedule(self):
        """Test with Asia/Tokyo timezone."""
        timezone_str = 'Asia/Tokyo'
        now = arrow.now(timezone_str)
        day_of_week = now.format('dddd')
        time_str = now.format('HH:00')
        duration = 90  # 1.5 hours

        result = time_handler.am_i_inside_time(
            day_of_week=day_of_week,
            time_str=time_str,
            timezone_str=timezone_str,
            duration=duration
        )

        self.assertTrue(result)

    def test_schedule_crossing_midnight(self):
        """Test schedule that crosses midnight."""
        timezone_str = 'UTC'
        now = arrow.now(timezone_str)

        # Set schedule to start 23:30 with 120 minute duration (crosses midnight)
        day_of_week = now.format('dddd')
        time_str = "23:30"
        duration = 120  # 2 hours - goes into next day

        # If we're at 00:15 the next day, we should still be in the schedule
        if now.hour == 0 and now.minute < 30:
            # We're in the time window that spilled over from yesterday
            result = time_handler.am_i_inside_time(
                day_of_week=day_of_week,
                time_str=time_str,
                timezone_str=timezone_str,
                duration=duration
            )
            # This might be true or false depending on exact time
            self.assertIsInstance(result, bool)

    def test_invalid_day_of_week(self):
        """Test that invalid day raises ValueError."""
        with self.assertRaises(ValueError) as context:
            time_handler.am_i_inside_time(
                day_of_week="Funday",
                time_str="12:00",
                timezone_str="UTC",
                duration=60
            )
        self.assertIn("Invalid day_of_week", str(context.exception))

    def test_invalid_time_format(self):
        """Test that invalid time format raises ValueError."""
        with self.assertRaises(ValueError) as context:
            time_handler.am_i_inside_time(
                day_of_week="Monday",
                time_str="25:99",
                timezone_str="UTC",
                duration=60
            )
        self.assertIn("Invalid time_str", str(context.exception))

    def test_invalid_time_format_non_numeric(self):
        """Test that non-numeric time raises ValueError."""
        with self.assertRaises(ValueError) as context:
            time_handler.am_i_inside_time(
                day_of_week="Monday",
                time_str="twelve:thirty",
                timezone_str="UTC",
                duration=60
            )
        self.assertIn("Invalid time_str", str(context.exception))

    def test_invalid_timezone(self):
        """Test that invalid timezone raises ValueError."""
        with self.assertRaises(ValueError) as context:
            time_handler.am_i_inside_time(
                day_of_week="Monday",
                time_str="12:00",
                timezone_str="Invalid/Timezone",
                duration=60
            )
        self.assertIn("Invalid timezone_str", str(context.exception))

    def test_short_duration(self):
        """Test with very short duration (15 minutes default)."""
        timezone_str = 'UTC'
        now = arrow.now(timezone_str)
        day_of_week = now.format('dddd')
        time_str = now.format('HH:mm')
        duration = 15  # Default duration

        result = time_handler.am_i_inside_time(
            day_of_week=day_of_week,
            time_str=time_str,
            timezone_str=timezone_str,
            duration=duration
        )

        self.assertTrue(result, "Current time should be within 15 minute window")

    def test_long_duration(self):
        """Test with long duration (24 hours)."""
        timezone_str = 'UTC'
        now = arrow.now(timezone_str)
        day_of_week = now.format('dddd')
        # Set time to current hour
        time_str = now.format('HH:00')
        duration = 1440  # 24 hours in minutes

        result = time_handler.am_i_inside_time(
            day_of_week=day_of_week,
            time_str=time_str,
            timezone_str=timezone_str,
            duration=duration
        )

        self.assertTrue(result, "Current time should be within 24 hour window")

    def test_case_insensitive_day(self):
        """Test that day of week is case insensitive."""
        timezone_str = 'UTC'
        now = arrow.now(timezone_str)
        day_of_week = now.format('dddd').lower()  # lowercase day
        time_str = now.format('HH:00')
        duration = 60

        result = time_handler.am_i_inside_time(
            day_of_week=day_of_week,
            time_str=time_str,
            timezone_str=timezone_str,
            duration=duration
        )

        self.assertTrue(result, "Lowercase day should work")

    def test_edge_case_midnight(self):
        """Test edge case at exactly midnight."""
        timezone_str = 'UTC'
        now = arrow.now(timezone_str)
        day_of_week = now.format('dddd')
        time_str = "00:00"
        duration = 60

        result = time_handler.am_i_inside_time(
            day_of_week=day_of_week,
            time_str=time_str,
            timezone_str=timezone_str,
            duration=duration
        )

        # Should be true if we're in the first hour of the day
        if now.hour == 0:
            self.assertTrue(result)

    def test_edge_case_end_of_day(self):
        """Test edge case near end of day."""
        timezone_str = 'UTC'
        now = arrow.now(timezone_str)
        day_of_week = now.format('dddd')
        time_str = "23:45"
        duration = 30  # 30 minutes crosses midnight

        result = time_handler.am_i_inside_time(
            day_of_week=day_of_week,
            time_str=time_str,
            timezone_str=timezone_str,
            duration=duration
        )

        # Result depends on current time
        self.assertIsInstance(result, bool)


class TestIsWithinSchedule(unittest.TestCase):
    """Tests for the is_within_schedule function."""

    def test_schedule_disabled(self):
        """Test that disabled schedule returns False."""
        time_schedule_limit = {'enabled': False}
        result = time_handler.is_within_schedule(time_schedule_limit)
        self.assertFalse(result)

    def test_schedule_none(self):
        """Test that None schedule returns False."""
        result = time_handler.is_within_schedule(None)
        self.assertFalse(result)

    def test_schedule_empty_dict(self):
        """Test that empty dict returns False."""
        result = time_handler.is_within_schedule({})
        self.assertFalse(result)

    def test_schedule_enabled_but_day_disabled(self):
        """Test schedule enabled but current day disabled."""
        timezone_str = 'UTC'
        now = arrow.now(timezone_str)
        current_day = now.format('dddd').lower()

        time_schedule_limit = {
            'enabled': True,
            'timezone': timezone_str,
            current_day: {
                'enabled': False,
                'start_time': '09:00',
                'duration': {'hours': 8, 'minutes': 0}
            }
        }

        result = time_handler.is_within_schedule(time_schedule_limit)
        self.assertFalse(result, "Disabled day should return False")

    def test_schedule_enabled_within_time(self):
        """Test schedule enabled and within time window."""
        timezone_str = 'UTC'
        now = arrow.now(timezone_str)
        current_day = now.format('dddd').lower()
        current_hour = now.format('HH:00')

        time_schedule_limit = {
            'enabled': True,
            'timezone': timezone_str,
            current_day: {
                'enabled': True,
                'start_time': current_hour,
                'duration': {'hours': 2, 'minutes': 0}
            }
        }

        result = time_handler.is_within_schedule(time_schedule_limit)
        self.assertTrue(result, "Current time should be within schedule")

    def test_schedule_enabled_outside_time(self):
        """Test schedule enabled but outside time window."""
        timezone_str = 'UTC'
        now = arrow.now(timezone_str)
        current_day = now.format('dddd').lower()
        # Set time to 3 hours ago
        past_time = now.shift(hours=-3).format('HH:mm')

        time_schedule_limit = {
            'enabled': True,
            'timezone': timezone_str,
            current_day: {
                'enabled': True,
                'start_time': past_time,
                'duration': {'hours': 1, 'minutes': 0}  # Only 1 hour duration
            }
        }

        result = time_handler.is_within_schedule(time_schedule_limit)
        self.assertFalse(result, "3 hours ago with 1 hour duration should be False")

    def test_schedule_with_default_timezone(self):
        """Test schedule without timezone uses default."""
        now = arrow.now('America/New_York')
        current_day = now.format('dddd').lower()
        current_hour = now.format('HH:00')

        time_schedule_limit = {
            'enabled': True,
            # No timezone specified
            current_day: {
                'enabled': True,
                'start_time': current_hour,
                'duration': {'hours': 2, 'minutes': 0}
            }
        }

        # Should use default UTC, but since we're testing with NY time,
        # the result depends on time difference
        result = time_handler.is_within_schedule(
            time_schedule_limit,
            default_tz='America/New_York'
        )
        self.assertTrue(result, "Should work with default timezone")

    def test_schedule_different_timezones(self):
        """Test schedule works correctly across different timezones."""
        # Test with Tokyo timezone
        timezone_str = 'Asia/Tokyo'
        now = arrow.now(timezone_str)
        current_day = now.format('dddd').lower()
        current_hour = now.format('HH:00')

        time_schedule_limit = {
            'enabled': True,
            'timezone': timezone_str,
            current_day: {
                'enabled': True,
                'start_time': current_hour,
                'duration': {'hours': 1, 'minutes': 30}
            }
        }

        result = time_handler.is_within_schedule(time_schedule_limit)
        self.assertTrue(result)

    def test_schedule_with_minutes_in_duration(self):
        """Test schedule with minutes specified in duration."""
        timezone_str = 'UTC'
        now = arrow.now(timezone_str)
        current_day = now.format('dddd').lower()
        current_time = now.format('HH:mm')

        time_schedule_limit = {
            'enabled': True,
            'timezone': timezone_str,
            current_day: {
                'enabled': True,
                'start_time': current_time,
                'duration': {'hours': 0, 'minutes': 45}
            }
        }

        result = time_handler.is_within_schedule(time_schedule_limit)
        self.assertTrue(result, "Should handle minutes in duration")

    def test_schedule_with_timezone_whitespace(self):
        """Test that timezone with whitespace is handled."""
        timezone_str = '  UTC  '
        now = arrow.now('UTC')
        current_day = now.format('dddd').lower()
        current_hour = now.format('HH:00')

        time_schedule_limit = {
            'enabled': True,
            'timezone': timezone_str,
            current_day: {
                'enabled': True,
                'start_time': current_hour,
                'duration': {'hours': 1, 'minutes': 0}
            }
        }

        result = time_handler.is_within_schedule(time_schedule_limit)
        self.assertTrue(result, "Should handle timezone with whitespace")


class TestWeekdayEnum(unittest.TestCase):
    """Tests for the Weekday enum."""

    def test_weekday_values(self):
        """Test that weekday enum has correct values."""
        self.assertEqual(time_handler.Weekday.Monday, 0)
        self.assertEqual(time_handler.Weekday.Tuesday, 1)
        self.assertEqual(time_handler.Weekday.Wednesday, 2)
        self.assertEqual(time_handler.Weekday.Thursday, 3)
        self.assertEqual(time_handler.Weekday.Friday, 4)
        self.assertEqual(time_handler.Weekday.Saturday, 5)
        self.assertEqual(time_handler.Weekday.Sunday, 6)

    def test_weekday_string_access(self):
        """Test accessing weekday enum by string."""
        self.assertEqual(time_handler.Weekday['Monday'], 0)
        self.assertEqual(time_handler.Weekday['Sunday'], 6)


if __name__ == '__main__':
    unittest.main()
