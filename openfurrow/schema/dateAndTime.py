# SPDX-License-Identifier: Apache-2.0
"""Dates and times of day as the record writes them: ISO 8601 and nothing else.

Left to themselves these types also read a number as seconds since 1970 or since
midnight, so a stray 0 would become a day in 1970 without a word. The record's dates are
written YYYY-MM-DD and its times HH:MM or HH:MM:SS (decision 0007); anything else is
refused where it enters. A time of day is the clock at the site and carries no zone.
"""

from __future__ import annotations

import datetime
import re
from typing import Annotated

from pydantic import BeforeValidator

_writtenDate = re.compile(r"\d{4}-\d{2}-\d{2}")
_writtenTime = re.compile(r"\d{2}:\d{2}(:\d{2})?")


def _requireWrittenDate(value: object) -> object:
  if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
    return value
  if isinstance(value, str) and _writtenDate.fullmatch(value):
    return value
  raise ValueError(f"a date is written YYYY-MM-DD, got {value!r}")


def _requireWrittenTime(value: object) -> object:
  if isinstance(value, datetime.time) and value.tzinfo is None and value.microsecond == 0:
    return value
  if isinstance(value, str) and _writtenTime.fullmatch(value):
    return value
  raise ValueError(f"a time of day is written HH:MM or HH:MM:SS, got {value!r}")


CalendarDate = Annotated[datetime.date, BeforeValidator(_requireWrittenDate)]
ClockTime = Annotated[datetime.time, BeforeValidator(_requireWrittenTime)]
