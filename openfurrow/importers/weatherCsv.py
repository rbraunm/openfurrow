# SPDX-License-Identifier: Apache-2.0
"""A trial's weather log, read from a CSV file (decision 0019, worklist REC-13).

One row per day. The `date` column is written YYYY-MM-DD. The measured columns are any of
rainfall, irrigation, minimumTemperature and maximumTemperature, each with its unit in
square brackets in the header (`rainfall [mm]`), so a unit is always stated, never
assumed; `notes` is text. Numbers use a decimal point; an empty cell is no value. Rows
may come in any order: the log is put in date order, and a day given twice is refused.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from pydantic import ValidationError

from openfurrow.schema.trialConditions import WeatherRecord

measuredColumns = ("rainfall", "irrigation", "minimumTemperature", "maximumTemperature")
_header = re.compile(r"^\s*(\w+)\s*(?:\[\s*([^\]]+?)\s*\])?\s*$")


class WeatherFileError(ValueError):
  """A weather file that cannot be read as a log of days."""


def readWeatherCsv(path: str | Path) -> list[WeatherRecord]:
  """The days a weather CSV lists, in date order. Raises WeatherFileError naming the problem."""
  with open(path, encoding="utf-8-sig", newline="") as handle:
    reader = csv.reader(handle)
    try:
      header = next(reader)
    except StopIteration as error:
      raise WeatherFileError("the weather file is empty") from error
    columns = []
    for text in header:
      match = _header.match(text)
      name, unit = (match.group(1), match.group(2)) if match else (text, None)
      if name in measuredColumns and unit is None:
        raise WeatherFileError(f"column '{text}' needs its unit in brackets, e.g. '{name} [mm]'")
      if name not in measuredColumns + ("date", "notes"):
        raise WeatherFileError(
          f"column '{text}' is not one of date, notes, or {', '.join(measuredColumns)} with a unit"
        )
      if name in ("date", "notes") and unit is not None:
        raise WeatherFileError(f"column '{text}' takes no unit")
      columns.append((name, unit))
    names = [name for name, _ in columns]
    if "date" not in names:
      raise WeatherFileError("the weather file has no date column")
    repeated = sorted({name for name in names if names.count(name) > 1})
    if repeated:
      raise WeatherFileError(f"columns given twice: {repeated}")
    records = []
    for rowNumber, cells in enumerate(reader, start=2):
      if not any(cell.strip() for cell in cells):
        continue
      if len(cells) != len(columns):
        raise WeatherFileError(f"row {rowNumber} has {len(cells)} cells, the header {len(columns)}")
      data: dict = {}
      for (name, unit), cell in zip(columns, cells):
        cell = cell.strip()
        if not cell:
          continue
        if name in measuredColumns:
          try:
            data[name] = {"value": float(cell), "unit": unit}
          except ValueError as error:
            raise WeatherFileError(f"row {rowNumber}: {name} '{cell}' is not a number") from error
        else:
          data[name] = cell
      try:
        records.append(WeatherRecord.model_validate(data))
      except ValidationError as error:
        problems = "; ".join(item["msg"] for item in error.errors())
        raise WeatherFileError(f"row {rowNumber}: {problems}") from error
  if not records:
    raise WeatherFileError("the weather file lists no days")
  records.sort(key=lambda record: record.date)
  days = [record.date for record in records]
  twice = sorted({day.isoformat() for day in days if days.count(day) > 1})
  if twice:
    raise WeatherFileError(f"days given more than once: {twice}")
  return records
