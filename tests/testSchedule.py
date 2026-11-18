# SPDX-License-Identifier: Apache-2.0
import datetime

import pytest

from openfurrow.tasks.schedule import Schedule, ScheduleError

UTC = datetime.UTC


def at(text):
  return datetime.datetime.fromisoformat(text).replace(tzinfo=UTC)


def runs(expression, start, count, zone="UTC"):
  schedule, moment, found = Schedule.read(expression, zone), at(start), []
  for _ in range(count):
    moment = schedule.nextAfter(moment)
    found.append(moment.isoformat())
  return found


@pytest.mark.parametrize("expression, start, expected", [
  ("*/15 * * * *", "2026-11-18 10:07", ["2026-11-18T10:15:00+00:00", "2026-11-18T10:30:00+00:00", "2026-11-18T10:45:00+00:00"]),
  ("0 */6 * * *", "2026-11-18 10:00", ["2026-11-18T12:00:00+00:00", "2026-11-18T18:00:00+00:00", "2026-11-19T00:00:00+00:00"]),
  ("30 2 * * mon-fri", "2026-11-20 03:00", ["2026-11-23T02:30:00+00:00", "2026-11-24T02:30:00+00:00", "2026-11-25T02:30:00+00:00"]),
  ("0 9 1 jan,jul *", "2026-11-18 00:00", ["2027-01-01T09:00:00+00:00", "2027-07-01T09:00:00+00:00", "2028-01-01T09:00:00+00:00"]),
  ("0 0 29 2 *", "2026-01-01 00:00", ["2028-02-29T00:00:00+00:00", "2032-02-29T00:00:00+00:00", "2036-02-29T00:00:00+00:00"]),
  ("0 12 13 * 5", "2026-11-01 00:00", ["2026-11-06T12:00:00+00:00", "2026-11-13T12:00:00+00:00", "2026-11-20T12:00:00+00:00"]),
  ("0 0 * * 7", "2026-11-18 00:00", ["2026-11-22T00:00:00+00:00", "2026-11-29T00:00:00+00:00", "2026-12-06T00:00:00+00:00"]),
  ("5-10/5 1 * * *", "2026-11-18 01:05", ["2026-11-18T01:10:00+00:00", "2026-11-19T01:05:00+00:00", "2026-11-19T01:10:00+00:00"]),
])
def testTheNextRunsAreTheOnesCronGives(expression, start, expected):
  assert runs(expression, start, 3) == expected


def testTimesAreReadInTheSchedulesZone():
  assert runs("0 6 * * *", "2026-11-18 00:00", 2, "America/Phoenix") == [
    "2026-11-18T13:00:00+00:00", "2026-11-19T13:00:00+00:00"]
  assert runs("0 6 * * *", "2026-11-18 00:00", 2, "Asia/Kolkata") == [
    "2026-11-18T00:30:00+00:00", "2026-11-19T00:30:00+00:00"]


def testATimeTheClockSkipsIsNotDueAndATimeItRepeatsIsDueOnce():
  assert runs("30 2 * * *", "2026-03-07 00:00", 2, "America/Denver") == [
    "2026-03-07T09:30:00+00:00", "2026-03-09T08:30:00+00:00"]
  assert runs("30 1 * * *", "2026-10-31 12:00", 2, "America/Denver") == [
    "2026-11-01T07:30:00+00:00", "2026-11-02T08:30:00+00:00"]


def testTheExpressionIsKeptInItsWrittenForm():
  assert Schedule.read(" 0   */6 * *  * ", "UTC").expression == "0 */6 * * *"


@pytest.mark.parametrize("expression, zone, why", [
  ("* * * *", "UTC", "has five fields"),
  ("60 * * * *", "UTC", "minute 60 is outside 0 to 59"),
  ("* 24 * * *", "UTC", "hour 24 is outside 0 to 23"),
  ("0 0 0 * *", "UTC", "day of month 0 is outside 1 to 31"),
  ("0 0 * 13 *", "UTC", "month 13 is outside 1 to 12"),
  ("0 0 * * 8", "UTC", "day of week 8 is outside 0 to 7"),
  ("*/0 * * * *", "UTC", "'0' is not a step"),
  ("5/2 * * * *", "UTC", "a step needs a range or"),
  ("10-5 * * * *", "UTC", "runs backwards"),
  ("1,,2 * * * *", "UTC", "'' is not a minute"),
  ("0 0 * * funday", "UTC", "'funday' is not a day of week"),
  ("0 0 31 2 *", "UTC", "is never due"),
  ("0 0 * * *", "Mars/Olympus", "is not a time zone"),
  ("١ * * * *", "UTC", "is not a minute"),
])
def testABadScheduleIsRefusedByName(expression, zone, why):
  with pytest.raises(ScheduleError, match=why):
    Schedule.read(expression, zone)


def testAMomentWithoutAZoneIsRefused():
  with pytest.raises(ValueError, match="carries its time zone"):
    Schedule.read("* * * * *", "UTC").nextAfter(datetime.datetime(2026, 1, 1))
