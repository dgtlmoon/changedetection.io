import os
from functools import lru_cache

from enum import IntEnum


def default_timezone_name(configured=None):
    """
    Resolve the scheduler's default IANA timezone name. Never returns None/''.

    `scheduler_timezone_default` is initialised to None in model/App.py, so the
    key always EXISTS with a None value. That makes the common idiom

        settings['application'].get('scheduler_timezone_default', os.getenv('TZ', 'UTC'))

    silently return None - dict.get() only falls back when the key is absent,
    not when its value is None. The None then reaches is_within_schedule(),
    which does `tz_name.strip()` and raises AttributeError.

    Args:
        configured: the stored setting value (may be None or empty)

    Returns:
        str: a non-empty timezone name, falling back to $TZ then 'UTC'
    """
    return (configured or os.getenv('TZ') or 'UTC').strip() or 'UTC'


class Weekday(IntEnum):
    """Enumeration for days of the week."""
    Monday = 0
    Tuesday = 1
    Wednesday = 2
    Thursday = 3
    Friday = 4
    Saturday = 5
    Sunday = 6

def am_i_inside_time(
        day_of_week: str,
        time_str: str,
        timezone_str: str,
        duration: int = 15,
) -> bool:
    """
    Determines if the current time falls within a specified time range.

    Parameters:
        day_of_week (str): The day of the week (e.g., 'Monday').
        time_str (str): The start time in 'HH:MM' format.
        timezone_str (str): The timezone identifier (e.g., 'Europe/Berlin').
        duration (int, optional): The duration of the time range in minutes. Default is 15.

    Returns:
        bool: True if the current time is within the time range, False otherwise.
    """
    import arrow
    # Parse the target day of the week
    try:
        target_weekday = Weekday[day_of_week.capitalize()]
    except KeyError:
        raise ValueError(f"Invalid day_of_week: '{day_of_week}'. Must be a valid weekday name.")

    # Parse the start time
    try:
        hour, minute = map(int, time_str.split(':'))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except (ValueError, AttributeError):
        raise ValueError(f"Invalid time_str: '{time_str}'. Must be in 'HH:MM' format.")

    # Get the current time in the specified timezone
    try:
        now_tz = arrow.now(timezone_str.strip())
    except Exception as e:
        raise ValueError(f"Invalid timezone_str: '{timezone_str}'. Must be a valid timezone identifier.")

    # Check if the current day matches the target day or overlaps due to duration
    current_weekday = now_tz.weekday()
    # Create start datetime for today in target timezone
    start_datetime_tz = now_tz.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # Handle previous day's overlap
    if target_weekday == (current_weekday - 1) % 7:
        # Calculate start and end times for the overlap from the previous day
        start_datetime_tz = start_datetime_tz.shift(days=-1)
        end_datetime_tz = start_datetime_tz.shift(minutes=duration)
        if start_datetime_tz <= now_tz <= end_datetime_tz:
            return True

    # Handle current day's range
    if target_weekday == current_weekday:
        end_datetime_tz = start_datetime_tz.shift(minutes=duration)
        if start_datetime_tz <= now_tz <= end_datetime_tz:
            return True

    # Handle next day's overlap
    if target_weekday == (current_weekday + 1) % 7:
        end_datetime_tz = start_datetime_tz.shift(minutes=duration)
        if now_tz < start_datetime_tz and now_tz.shift(days=1) <= end_datetime_tz:
            return True

    return False


def is_within_schedule(time_schedule_limit, default_tz="UTC"):
    """
    Check if the current time is within a scheduled time window.

    Parameters:
        time_schedule_limit (TimeScheduleLimit|dict): Schedule configuration with timezone, day settings, etc.
            A watch/tag holds the typed model, global settings still hold a dict.
        default_tz (str): Default timezone to use if not specified. Default is 'UTC'.

    Returns:
        bool: True if current time is within the schedule, False otherwise.
    """
    import arrow
    from changedetectionio.model.TimeScheduleLimit import as_time_schedule_limit

    time_schedule_limit = as_time_schedule_limit(time_schedule_limit)
    if time_schedule_limit.enabled:
        # Get the timezone the time schedule is in, so we know what day it is there
        tz_name = time_schedule_limit.timezone
        if not tz_name:
            tz_name = default_tz

        # Get current day name in the target timezone
        now_day_name_in_tz = arrow.now(tz_name.strip()).format('dddd')
        selected_day_schedule = time_schedule_limit.day(now_day_name_in_tz)
        if not selected_day_schedule.enabled:
            return False

        duration = selected_day_schedule.duration
        selected_day_run_duration_m = duration.hours * 60 + duration.minutes

        is_valid = am_i_inside_time(day_of_week=now_day_name_in_tz,
                                    time_str=selected_day_schedule.start_time,
                                    timezone_str=tz_name,
                                    duration=selected_day_run_duration_m)

        return is_valid

    return False
