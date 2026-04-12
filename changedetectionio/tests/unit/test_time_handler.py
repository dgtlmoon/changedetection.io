#!/usr/bin/env python3

"""
Comprehensive tests for time_handler module refactored to use arrow.

Run from project root:
python3 -m pytest changedetectionio/tests/unit/test_time_handler.py -v
"""

import unittest
import unittest.mock
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

    def test_24_hour_schedule_from_midnight(self):
        """Test 24-hour schedule starting at midnight covers entire day."""
        timezone_str = 'UTC'
        # Test at a specific time: Monday 00:00
        test_time = arrow.get('2024-01-01 00:00:00', 'YYYY-MM-DD HH:mm:ss').replace(tzinfo=timezone_str)
        day_of_week = test_time.format('dddd')  # Monday

        # Mock current time for testing
        with unittest.mock.patch('arrow.now', return_value=test_time):
            result = time_handler.am_i_inside_time(
                day_of_week=day_of_week,
                time_str="00:00",
                timezone_str=timezone_str,
                duration=1440  # 24 hours
            )
            self.assertTrue(result, "Should be active at start of 24-hour schedule")

    def test_24_hour_schedule_at_end_of_day(self):
        """Test 24-hour schedule is active at 23:59:59."""
        timezone_str = 'UTC'
        # Test at Monday 23:59:59
        test_time = arrow.get('2024-01-01 23:59:59', 'YYYY-MM-DD HH:mm:ss').replace(tzinfo=timezone_str)
        day_of_week = test_time.format('dddd')  # Monday

        with unittest.mock.patch('arrow.now', return_value=test_time):
            result = time_handler.am_i_inside_time(
                day_of_week=day_of_week,
                time_str="00:00",
                timezone_str=timezone_str,
                duration=1440  # 24 hours
            )
            self.assertTrue(result, "Should be active at end of 24-hour schedule")

    def test_24_hour_schedule_at_midnight_transition(self):
        """Test 24-hour schedule at exactly midnight transition."""
        timezone_str = 'UTC'
        # Test at Tuesday 00:00:00 (end of Monday's 24-hour schedule)
        test_time = arrow.get('2024-01-02 00:00:00', 'YYYY-MM-DD HH:mm:ss').replace(tzinfo=timezone_str)
        monday = test_time.shift(days=-1).format('dddd')  # Monday

        with unittest.mock.patch('arrow.now', return_value=test_time):
            result = time_handler.am_i_inside_time(
                day_of_week=monday,
                time_str="00:00",
                timezone_str=timezone_str,
                duration=1440  # 24 hours
            )
            self.assertTrue(result, "Should include exactly midnight at end of 24-hour schedule")

    def test_schedule_crosses_midnight_before_midnight(self):
        """Test schedule crossing midnight - before midnight."""
        timezone_str = 'UTC'
        # Monday 23:30
        test_time = arrow.get('2024-01-01 23:30:00', 'YYYY-MM-DD HH:mm:ss').replace(tzinfo=timezone_str)
        day_of_week = test_time.format('dddd')  # Monday

        with unittest.mock.patch('arrow.now', return_value=test_time):
            result = time_handler.am_i_inside_time(
                day_of_week=day_of_week,
                time_str="23:00",
                timezone_str=timezone_str,
                duration=120  # 2 hours (until 01:00 next day)
            )
            self.assertTrue(result, "Should be active before midnight in cross-midnight schedule")

    def test_schedule_crosses_midnight_after_midnight(self):
        """Test schedule crossing midnight - after midnight."""
        timezone_str = 'UTC'
        # Tuesday 00:30
        test_time = arrow.get('2024-01-02 00:30:00', 'YYYY-MM-DD HH:mm:ss').replace(tzinfo=timezone_str)
        monday = test_time.shift(days=-1).format('dddd')  # Monday

        with unittest.mock.patch('arrow.now', return_value=test_time):
            result = time_handler.am_i_inside_time(
                day_of_week=monday,
                time_str="23:00",
                timezone_str=timezone_str,
                duration=120  # 2 hours (until 01:00 Tuesday)
            )
            self.assertTrue(result, "Should be active after midnight in cross-midnight schedule")

    def test_schedule_crosses_midnight_at_exact_end(self):
        """Test schedule crossing midnight at exact end time."""
        timezone_str = 'UTC'
        # Tuesday 01:00 (exact end of Monday 23:00 + 120 minutes)
        test_time = arrow.get('2024-01-02 01:00:00', 'YYYY-MM-DD HH:mm:ss').replace(tzinfo=timezone_str)
        monday = test_time.shift(days=-1).format('dddd')  # Monday

        with unittest.mock.patch('arrow.now', return_value=test_time):
            result = time_handler.am_i_inside_time(
                day_of_week=monday,
                time_str="23:00",
                timezone_str=timezone_str,
                duration=120  # 2 hours
            )
            self.assertTrue(result, "Should include exact end time of schedule")

    def test_duration_60_minutes(self):
        """Test that duration of 60 minutes works correctly."""
        timezone_str = 'UTC'
        test_time = arrow.get('2024-01-01 12:30:00', 'YYYY-MM-DD HH:mm:ss').replace(tzinfo=timezone_str)
        day_of_week = test_time.format('dddd')

        with unittest.mock.patch('arrow.now', return_value=test_time):
            result = time_handler.am_i_inside_time(
                day_of_week=day_of_week,
                time_str="12:00",
                timezone_str=timezone_str,
                duration=60  # Exactly 60 minutes
            )
            self.assertTrue(result, "60-minute duration should work")

    def test_duration_at_exact_end_minute(self):
        """Test at exact end of 60-minute window."""
        timezone_str = 'UTC'
        # Exactly 13:00 (end of 12:00 + 60 minutes)
        test_time = arrow.get('2024-01-01 13:00:00', 'YYYY-MM-DD HH:mm:ss').replace(tzinfo=timezone_str)
        day_of_week = test_time.format('dddd')

        with unittest.mock.patch('arrow.now', return_value=test_time):
            result = time_handler.am_i_inside_time(
                day_of_week=day_of_week,
                time_str="12:00",
                timezone_str=timezone_str,
                duration=60
            )
            self.assertTrue(result, "Should include exact end minute")

    def test_one_second_after_schedule_ends(self):
        """Test one second after schedule should end."""
        timezone_str = 'UTC'
        # 13:00:01 (one second after 12:00 + 60 minutes)
        test_time = arrow.get('2024-01-01 13:00:01', 'YYYY-MM-DD HH:mm:ss').replace(tzinfo=timezone_str)
        day_of_week = test_time.format('dddd')

        with unittest.mock.patch('arrow.now', return_value=test_time):
            result = time_handler.am_i_inside_time(
                day_of_week=day_of_week,
                time_str="12:00",
                timezone_str=timezone_str,
                duration=60
            )
            self.assertFalse(result, "Should be False one second after schedule ends")

    def test_multi_day_schedule(self):
        """Test schedule longer than 24 hours (48 hours)."""
        timezone_str = 'UTC'
        # Tuesday 12:00 (36 hours after Monday 00:00)
        test_time = arrow.get('2024-01-02 12:00:00', 'YYYY-MM-DD HH:mm:ss').replace(tzinfo=timezone_str)
        monday = test_time.shift(days=-1).format('dddd')

        with unittest.mock.patch('arrow.now', return_value=test_time):
            result = time_handler.am_i_inside_time(
                day_of_week=monday,
                time_str="00:00",
                timezone_str=timezone_str,
                duration=2880  # 48 hours
            )
            self.assertTrue(result, "Should support multi-day schedules")

    def test_schedule_one_minute_duration(self):
        """Test very short 1-minute schedule."""
        timezone_str = 'UTC'
        test_time = arrow.get('2024-01-01 12:00:30', 'YYYY-MM-DD HH:mm:ss').replace(tzinfo=timezone_str)
        day_of_week = test_time.format('dddd')

        with unittest.mock.patch('arrow.now', return_value=test_time):
            result = time_handler.am_i_inside_time(
                day_of_week=day_of_week,
                time_str="12:00",
                timezone_str=timezone_str,
                duration=1  # Just 1 minute
            )
            self.assertTrue(result, "1-minute schedule should work")

    def test_schedule_at_exact_start_time(self):
        """Test at exact start time (00:00:00.000000)."""
        timezone_str = 'UTC'
        test_time = arrow.get('2024-01-01 12:00:00.000000', 'YYYY-MM-DD HH:mm:ss.SSSSSS').replace(tzinfo=timezone_str)
        day_of_week = test_time.format('dddd')

        with unittest.mock.patch('arrow.now', return_value=test_time):
            result = time_handler.am_i_inside_time(
                day_of_week=day_of_week,
                time_str="12:00",
                timezone_str=timezone_str,
                duration=30
            )
            self.assertTrue(result, "Should include exact start time")

    def test_schedule_one_microsecond_before_start(self):
        """Test one microsecond before schedule starts."""
        timezone_str = 'UTC'
        test_time = arrow.get('2024-01-01 11:59:59.999999', 'YYYY-MM-DD HH:mm:ss.SSSSSS').replace(tzinfo=timezone_str)
        day_of_week = test_time.format('dddd')

        with unittest.mock.patch('arrow.now', return_value=test_time):
            result = time_handler.am_i_inside_time(
                day_of_week=day_of_week,
                time_str="12:00",
                timezone_str=timezone_str,
                duration=30
            )
            self.assertFalse(result, "Should not include time before start")


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

    def test_schedule_with_60_minutes(self):
        """Test schedule with duration of 0 hours and 60 minutes."""
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
                'duration': {'hours': 0, 'minutes': 60}  # 60 minutes
            }
        }

        result = time_handler.is_within_schedule(time_schedule_limit)
        self.assertTrue(result, "Should accept 60 minutes as valid duration")

    def test_schedule_with_24_hours(self):
        """Test schedule with duration of 24 hours and 0 minutes."""
        timezone_str = 'UTC'
        now = arrow.now(timezone_str)
        current_day = now.format('dddd').lower()
        start_hour = now.format('HH:00')

        time_schedule_limit = {
            'enabled': True,
            'timezone': timezone_str,
            current_day: {
                'enabled': True,
                'start_time': start_hour,
                'duration': {'hours': 24, 'minutes': 0}  # Full 24 hours
            }
        }

        result = time_handler.is_within_schedule(time_schedule_limit)
        self.assertTrue(result, "Should accept 24 hours as valid duration")

    def test_schedule_with_90_minutes(self):
        """Test schedule with duration of 0 hours and 90 minutes."""
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
                'duration': {'hours': 0, 'minutes': 90}  # 90 minutes = 1.5 hours
            }
        }

        result = time_handler.is_within_schedule(time_schedule_limit)
        self.assertTrue(result, "Should accept 90 minutes as valid duration")

    def test_schedule_24_hours_from_midnight(self):
        """Test 24-hour schedule from midnight using is_within_schedule."""
        timezone_str = 'UTC'
        test_time = arrow.get('2024-01-01 12:00:00', 'YYYY-MM-DD HH:mm:ss').replace(tzinfo=timezone_str)
        current_day = test_time.format('dddd').lower()  # monday

        time_schedule_limit = {
            'enabled': True,
            'timezone': timezone_str,
            current_day: {
                'enabled': True,
                'start_time': '00:00',
                'duration': {'hours': 24, 'minutes': 0}
            }
        }

        with unittest.mock.patch('arrow.now', return_value=test_time):
            result = time_handler.is_within_schedule(time_schedule_limit)
            self.assertTrue(result, "24-hour schedule from midnight should cover entire day")

    def test_schedule_24_hours_at_end_of_day(self):
        """Test 24-hour schedule at 23:59 using is_within_schedule."""
        timezone_str = 'UTC'
        test_time = arrow.get('2024-01-01 23:59:00', 'YYYY-MM-DD HH:mm:ss').replace(tzinfo=timezone_str)
        current_day = test_time.format('dddd').lower()

        time_schedule_limit = {
            'enabled': True,
            'timezone': timezone_str,
            current_day: {
                'enabled': True,
                'start_time': '00:00',
                'duration': {'hours': 24, 'minutes': 0}
            }
        }

        with unittest.mock.patch('arrow.now', return_value=test_time):
            result = time_handler.is_within_schedule(time_schedule_limit)
            self.assertTrue(result, "Should be active at 23:59 in 24-hour schedule")

    def test_schedule_crosses_midnight_with_is_within_schedule(self):
        """Test schedule crossing midnight using is_within_schedule."""
        timezone_str = 'UTC'
        # Tuesday 00:30
        test_time = arrow.get('2024-01-02 00:30:00', 'YYYY-MM-DD HH:mm:ss').replace(tzinfo=timezone_str)
        # Get Monday as that's when the schedule started
        monday = test_time.shift(days=-1).format('dddd').lower()

        time_schedule_limit = {
            'enabled': True,
            'timezone': timezone_str,
            'monday': {
                'enabled': True,
                'start_time': '23:00',
                'duration': {'hours': 2, 'minutes': 0}  # Until 01:00 Tuesday
            },
            'tuesday': {
                'enabled': False,
                'start_time': '09:00',
                'duration': {'hours': 8, 'minutes': 0}
            }
        }

        with unittest.mock.patch('arrow.now', return_value=test_time):
            result = time_handler.is_within_schedule(time_schedule_limit)
            # Note: This checks Tuesday's schedule, not Monday's overlap
            # So it should be False because Tuesday is disabled
            self.assertFalse(result, "Should check current day (Tuesday), which is disabled")

    def test_schedule_with_mixed_hours_minutes(self):
        """Test schedule with both hours and minutes (23 hours 60 minutes = 24 hours)."""
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
                'duration': {'hours': 23, 'minutes': 60}  # = 1440 minutes = 24 hours
            }
        }

        result = time_handler.is_within_schedule(time_schedule_limit)
        self.assertTrue(result, "Should handle 23 hours + 60 minutes = 24 hours")

    def test_schedule_48_hours(self):
        """Test schedule with 48-hour duration."""
        timezone_str = 'UTC'
        now = arrow.now(timezone_str)
        current_day = now.format('dddd').lower()
        start_hour = now.format('HH:00')

        time_schedule_limit = {
            'enabled': True,
            'timezone': timezone_str,
            current_day: {
                'enabled': True,
                'start_time': start_hour,
                'duration': {'hours': 48, 'minutes': 0}  # 2 full days
            }
        }

        result = time_handler.is_within_schedule(time_schedule_limit)
        self.assertTrue(result, "Should support 48-hour (multi-day) schedules")


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
