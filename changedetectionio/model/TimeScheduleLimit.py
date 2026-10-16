"""
Typed model for the weekly check schedule, stored at
    watch['time_schedule_limit'] / tag['time_schedule_limit']
and (still as a plain dict for now) at
    datastore.data['settings']['requests']['time_schedule_limit']

Untouched days share one DaySchedule instance across every watch, see shared_defaults.py
"""
from typing import ClassVar, Optional

from loguru import logger
from pydantic import Field, ValidationError
from pydantic.dataclasses import dataclass

from .shared_defaults import DefaultShared

DAYS_OF_WEEK = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')


@dataclass(slots=True, frozen=True)
class Duration(DefaultShared):
    BLANK_MEANS_DEFAULT: ClassVar[bool] = True
    # No upper bound, multi-day windows (e.g. 48 hours) are supported by time_handler
    hours: int = Field(default=24, ge=0)
    minutes: int = Field(default=0, ge=0)


@dataclass(slots=True, frozen=True)
class DaySchedule(DefaultShared):
    BLANK_MEANS_DEFAULT: ClassVar[bool] = True
    enabled: bool = True
    start_time: str = Field(default='00:00', pattern=r'^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$')
    duration: Duration = Duration()


@dataclass(slots=True, frozen=True)
class TimeScheduleLimit(DefaultShared):
    BLANK_MEANS_DEFAULT: ClassVar[bool] = True  # e.g. the form submits timezone '' for "not set"
    enabled: bool = False
    timezone: Optional[str] = None
    monday: DaySchedule = DaySchedule()
    tuesday: DaySchedule = DaySchedule()
    wednesday: DaySchedule = DaySchedule()
    thursday: DaySchedule = DaySchedule()
    friday: DaySchedule = DaySchedule()
    saturday: DaySchedule = DaySchedule()
    sunday: DaySchedule = DaySchedule()

    def day(self, day_name):
        return getattr(self, day_name.lower())


DEFAULT_TIME_SCHEDULE_LIMIT = TimeScheduleLimit()


def as_time_schedule_limit(value, owner_uuid=None):
    """
    Anything stored or submitted -> TimeScheduleLimit, values equal to the default become
    the shared DEFAULT_TIME_SCHEDULE_LIMIT.

    Lenient on purpose, this runs while loading watch.json. A broken stored value must not
    stop the watch from loading, so it falls back to the default and logs. Blank/None fields
    already fall back to their own default (BLANK_MEANS_DEFAULT), so this only happens for
    genuinely unparseable values. The API checks input strictly before it gets here
    (api/Watch.py validate_time_schedule_limit()).

    owner_uuid is only for the log line, so the right watch/tag can be restored from a backup.
    """
    if not value:
        return DEFAULT_TIME_SCHEDULE_LIMIT
    try:
        schedule = TimeScheduleLimit.validate(value)
    except ValidationError as e:
        logger.error(f"{owner_uuid or 'Unknown watch/tag'} - Invalid time_schedule_limit {value!r}, using the default (no schedule) - {e}")
        return DEFAULT_TIME_SCHEDULE_LIMIT
    return DEFAULT_TIME_SCHEDULE_LIMIT if schedule == DEFAULT_TIME_SCHEDULE_LIMIT else schedule
