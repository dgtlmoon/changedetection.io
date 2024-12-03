from datetime import timedelta, datetime
from enum import IntEnum
from zoneinfo import ZoneInfo


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
    # Parse the target day of the week
    try:
        target_weekday = Weekday[day_of_week.capitalize()]
    except KeyError:
        raise ValueError(f"Invalid day_of_week: '{day_of_week}'. Must be a valid weekday name.")

    # Parse the start time
    try:
        target_time = datetime.strptime(time_str, '%H:%M').time()
    except ValueError:
        raise ValueError(f"Invalid time_str: '{time_str}'. Must be in 'HH:MM' format.")

    # Define the timezone
    try:
        tz = ZoneInfo(timezone_str)
    except Exception:
        raise ValueError(f"Invalid timezone_str: '{timezone_str}'. Must be a valid timezone identifier.")

    # Get the current time in the specified timezone
    now_tz = datetime.now(tz)

    # Check if the current day matches the target day or overlaps due to duration
    current_weekday = now_tz.weekday()
    start_datetime_tz = datetime.combine(now_tz.date(), target_time, tzinfo=tz)

    # Handle previous day's overlap
    if target_weekday == (current_weekday - 1) % 7:
        # Calculate start and end times for the overlap from the previous day
        start_datetime_tz -= timedelta(days=1)
        end_datetime_tz = start_datetime_tz + timedelta(minutes=duration)
        if start_datetime_tz <= now_tz < end_datetime_tz:
            return True

    # Handle current day's range
    if target_weekday == current_weekday:
        end_datetime_tz = start_datetime_tz + timedelta(minutes=duration)
        if start_datetime_tz <= now_tz < end_datetime_tz:
            return True

    # Handle next day's overlap
    if target_weekday == (current_weekday + 1) % 7:
        end_datetime_tz = start_datetime_tz + timedelta(minutes=duration)
        if now_tz < start_datetime_tz and now_tz + timedelta(days=1) < end_datetime_tz:
            return True

    return False


def is_within_schedule(time_schedule_limit, default_tz="UTC"):
    if time_schedule_limit and time_schedule_limit.get('enabled'):
        # Get the timezone the time schedule is in, so we know what day it is there
        tz_name = time_schedule_limit.get('timezone')
        if not tz_name:
            tz_name = default_tz

        now_day_name_in_tz = datetime.now(ZoneInfo(tz_name.strip())).strftime('%A')
        selected_day_schedule = time_schedule_limit.get(now_day_name_in_tz.lower())
        if not selected_day_schedule.get('enabled'):
            return False

        duration = selected_day_schedule.get('duration')
        selected_day_run_duration_m = int(duration.get('hours')) * 60 + int(duration.get('minutes'))

        is_valid = am_i_inside_time(day_of_week=now_day_name_in_tz,
                                    time_str=selected_day_schedule['start_time'],
                                    timezone_str=tz_name,
                                    duration=selected_day_run_duration_m)

        return is_valid

    return False
