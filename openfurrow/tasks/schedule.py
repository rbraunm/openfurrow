# SPDX-License-Identifier: Apache-2.0
"""Five-field cron schedules (decision 0041): minute, hour, day of month, month, day of week.

Each field is `*`, a number, a range `a-b`, a step `*/s` or `a-b/s`, or a comma list of
those; months and days of the week may be named (jan..dec, sun..sat), and day of week 7 is
Sunday as 0 is. As in cron, when both the day of month and the day of week are restricted,
a day matching either one is due. Times are wall-clock times in the schedule's zone: a time
that does not exist that day (the hour a clock skips forward) is not due, and a time that
happens twice (the hour a clock goes back) is due once, at its first occurrence.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from zoneinfo import ZoneInfo

_fieldNames = ("minute", "hour", "day of month", "month", "day of week")
_bounds = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
_monthNames = {name: number for number, name in enumerate(
  ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}
_dayNames = {name: number for number, name in enumerate(("sun", "mon", "tue", "wed", "thu", "fri", "sat"))}
_searchYears = 29


class ScheduleError(ValueError):
  """A schedule that is not a five-field cron expression, or that is never due."""


def _value(text: str, field: int) -> int:
  names = _monthNames if field == 3 else _dayNames if field == 4 else {}
  if text.lower() in names:
    return names[text.lower()]
  if not text.isascii() or not text.isdigit():
    raise ScheduleError(f"'{text}' is not a {_fieldNames[field]}")
  number = int(text)
  low, high = _bounds[field]
  if not low <= number <= high:
    raise ScheduleError(f"{_fieldNames[field]} {number} is outside {low} to {high}")
  return number


def _field(text: str, field: int) -> tuple[frozenset[int], bool]:
  """The values a field allows, and whether it is restricted (anything but a bare `*`)."""
  low, high = _bounds[field]
  values: set[int] = set()
  for part in text.split(","):
    span, slash, stepText = part.partition("/")
    step = 1
    if slash:
      if not stepText.isascii() or not stepText.isdigit() or int(stepText) == 0:
        raise ScheduleError(f"'{stepText}' is not a step in the {_fieldNames[field]} field")
      step = int(stepText)
    if span == "*":
      first, last = low, high
    elif "-" in span:
      startText, _, endText = span.partition("-")
      first, last = _value(startText, field), _value(endText, field)
      if first > last:
        raise ScheduleError(f"the {_fieldNames[field]} range {span} runs backwards")
    elif slash:
      raise ScheduleError(f"a step needs a range or *, not '{part}'")
    else:
      first = last = _value(span, field)
    values.update(range(first, last + 1, step))
  if field == 4 and 7 in values:
    values = (values - {7}) | {0}
  return frozenset(values), text != "*"


@dataclass(frozen=True)
class Schedule:
  expression: str
  zone: str
  minutes: frozenset[int]
  hours: frozenset[int]
  days: frozenset[int]
  months: frozenset[int]
  weekdays: frozenset[int]
  daysRestricted: bool
  weekdaysRestricted: bool

  @classmethod
  def read(cls, expression: str, zone: str) -> Schedule:
    fields = expression.split()
    if len(fields) != 5:
      raise ScheduleError(f"a schedule has five fields (minute hour day month weekday), not {len(fields)}: '{expression}'")
    try:
      ZoneInfo(zone)
    except (ValueError, KeyError) as error:
      raise ScheduleError(f"'{zone}' is not a time zone: {error}") from None
    parsed = [_field(text, index) for index, text in enumerate(fields)]
    schedule = cls(" ".join(fields), zone, parsed[0][0], parsed[1][0], parsed[2][0], parsed[3][0], parsed[4][0],
                   parsed[2][1], parsed[4][1])
    schedule.nextAfter(datetime.datetime(2000, 1, 1, tzinfo=datetime.UTC))
    return schedule

  def _dayIsDue(self, day: datetime.date) -> bool:
    if day.month not in self.months:
      return False
    onDay, onWeekday = day.day in self.days, (day.isoweekday() % 7) in self.weekdays
    if self.daysRestricted and self.weekdaysRestricted:
      return onDay or onWeekday
    return onDay and onWeekday

  def nextAfter(self, moment: datetime.datetime) -> datetime.datetime:
    """The first due time strictly after `moment` (which must carry its zone), in UTC."""
    if moment.tzinfo is None:
      raise ValueError("a moment carries its time zone")
    zone = ZoneInfo(self.zone)
    local = moment.astimezone(zone)
    day = local.date()
    for _ in range(_searchYears * 366):
      if self._dayIsDue(day):
        for hour in sorted(self.hours):
          for minute in sorted(self.minutes):
            wall = datetime.datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)
            if wall.astimezone(datetime.UTC).astimezone(zone).replace(tzinfo=None) != wall.replace(tzinfo=None):
              continue
            if wall > moment:
              return wall.astimezone(datetime.UTC)
      day += datetime.timedelta(days=1)
    raise ScheduleError(f"the schedule '{self.expression}' is never due")
