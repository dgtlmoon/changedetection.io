from datetime import datetime, timedelta, time, date
from zoneinfo import ZoneInfo
from enum import IntEnum
from typing import Optional

class Weekday(IntEnum):
    """Enumeration for days of the week."""
    Monday = 0
    Tuesday = 1
    Wednesday = 2
    Thursday = 3
    Friday = 4
    Saturday = 5
    Sunday = 6


def get_previous_day_name(current_day_name: str) -> str:
    """
    Returns the previous day name given the current day name.

    Parameters:
        current_day_name (str): The current day name (e.g., 'Monday').

    Returns:
        str: The name of the previous day.
    """
    # Normalize the day name to match the Enum member names
    normalized_day_name = current_day_name.capitalize()

    # Get the current day enum
    try:
        current_day_enum = Weekday[normalized_day_name]
    except KeyError:
        raise ValueError(f"Invalid day name: '{current_day_name}'. Please provide a valid weekday name.")

    # Calculate the previous day using modulo arithmetic
    previous_day_enum = Weekday((current_day_enum - 1) % 7)

    # Return the name of the previous day
    return previous_day_enum.name

def get_most_recent_day_time(
    now: datetime,
    target_weekday: Weekday,
    target_time: time,
    tz: ZoneInfo
) -> datetime:
    """
    Calculates the most recent past occurrence of a specific day and time in a given timezone.

    Parameters:
        now (datetime): The current datetime in the target timezone.
        target_weekday (Weekday): The target day of the week.
        target_time (time): The target time.
        tz (ZoneInfo): The timezone object.

    Returns:
        datetime: The datetime object representing the most recent occurrence.
    """
    # Calculate the date of the most recent target weekday
    days_since_target = (now.weekday() - target_weekday) % 7
    target_date: date = now.date() - timedelta(days=days_since_target)

    # Combine the target date and time
    target_datetime = datetime.combine(target_date, target_time, tzinfo=tz)

    # If the target datetime is in the future, subtract 7 days to get the most recent past occurrence
    if now < target_datetime:
        target_datetime -= timedelta(days=7)

    return target_datetime

def am_i_inside_time(
    day_of_week: str,
    time_str: str,
    timezone_str: str,
    duration: int = 15,
    now_utc: Optional[datetime] = None
) -> bool:
    """
    Determines if the current time falls within a specified time range.

    Parameters:
        day_of_week (str): The day of the week (e.g., 'Monday').
        time_str (str): The start time in 'HH:MM' format.
        timezone_str (str): The timezone identifier (e.g., 'America/New_York').
        duration (int, optional): The duration of the time range in minutes. Default is 15.
        now_utc (datetime, optional): The current UTC time. If None, uses the actual current UTC time.

    Returns:
        bool: True if the current time is within the time range, False otherwise.
    """
    # Parse the day of the week using the Weekday Enum
    try:
        target_weekday = Weekday[day_of_week]
    except KeyError:
        raise ValueError(f"Invalid day_of_week: '{day_of_week}'. Must be a valid weekday name.")

    # Parse the target time
    try:
        target_time = datetime.strptime(time_str, '%H:%M').time()
    except ValueError:
        raise ValueError(f"Invalid time_str: '{time_str}'. Must be in 'HH:MM' format.")

    # Define the timezone
    try:
        tz = ZoneInfo(timezone_str)
    except ZoneInfo.KeyError:
        raise ValueError(f"Invalid timezone_str: '{timezone_str}'. Must be a valid timezone identifier.")

    # Use the provided 'now_utc' or get the current UTC time
    if now_utc is None:
        now_utc = datetime.now(tz=ZoneInfo('UTC'))

    # Convert the current UTC time to the target timezone
    now_tz = now_utc.astimezone(tz)

    # Calculate the start datetime in the target timezone
    start_datetime_tz = get_most_recent_day_time(now_tz, target_weekday, target_time, tz)

    # Calculate the end datetime by adding the duration
    end_datetime_tz = start_datetime_tz + timedelta(minutes=duration)

    # Convert start and end times to UTC for accurate comparison
    start_datetime_utc = start_datetime_tz.astimezone(ZoneInfo('UTC'))
    end_datetime_utc = end_datetime_tz.astimezone(ZoneInfo('UTC'))

    # Determine if the current UTC time is within the time range
    is_inside = start_datetime_utc <= now_utc < end_datetime_utc

    return is_inside

# Example usage:
if __name__ == "__main__":
    # Parameters
    day_of_week = 'Monday'
    time_str = '12:00'
    timezone_str = 'Europe/Berlin'

    #timezone_str = 'UTC'
    duration = 60  # Duration in minutes


    # 12:00 berlin is 11:00 UTC
    # Lucky, 1-1-2024 is monday also
    UTC_test_datetime = datetime(2024, 1, 1, 11, 10, tzinfo=ZoneInfo('UTC'))

    # Check if we are inside the time range
    result = am_i_inside_time(day_of_week=day_of_week,
                              time_str=time_str,
                              timezone_str=timezone_str,
                              duration=duration,
                              now_utc=UTC_test_datetime)

    print(f"Are we inside the time range? {day_of_week} {time_str} within {timezone_str} with {duration} minutes.. compared to {UTC_test_datetime} ({UTC_test_datetime.strftime('%A')})- {'Yes' if result else 'No'}")

    # @todo integrate get_previous_day_name