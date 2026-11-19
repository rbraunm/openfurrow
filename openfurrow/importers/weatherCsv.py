# SPDX-License-Identifier: Apache-2.0
"""A trial's weather log, read from a CSV file (decision 0019, worklist REC-13).

One row per day. The `date` column is written YYYY-MM-DD. The measured columns are any of
rainfall, irrigation, minimumTemperature and maximumTemperature, each with its unit in
square brackets in the header (`rainfall [mm]`), so a unit is always stated, never
assumed; `notes` is text. Numbers use a decimal point; an empty cell is no value. Rows
may come in any order: the log is put in date order, and a day given twice is refused.

The file is read from its bytes, the form an import keeps it in (decision 0044), and the
result says what each column was read as.
"""

from __future__ import annotations

import csv
import io
import re

from pydantic import BaseModel, ConfigDict, ValidationError

from openfurrow.schema.trialConditions import WeatherRecord

measuredColumns = ("rainfall", "irrigation", "minimumTemperature", "maximumTemperature")
_header = re.compile(r"^\s*(\w+)\s*(?:\[\s*([^\]]+?)\s*\])?\s*$")


class WeatherFileError(ValueError):
  """A weather file that cannot be read as a log of days."""


class WeatherColumn(BaseModel):
  """A column of a weather file: its header as written, the fact it holds, and the unit the header states."""

  model_config = ConfigDict(extra="forbid")

  column: str
  field: str
  unit: str | None = None


class WeatherFile(BaseModel):
  model_config = ConfigDict(extra="forbid")

  records: list[WeatherRecord]
  columns: list[WeatherColumn]


def readWeatherCsv(data: bytes) -> WeatherFile:
  """The days a weather CSV lists, in date order, and its columns. Raises WeatherFileError naming the problem."""
  try:
    reader = csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""))
  except UnicodeDecodeError as error:
    raise WeatherFileError(f"the weather file is not UTF-8 text (byte {error.start}); save it as CSV UTF-8") from error
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
    columns.append(WeatherColumn(column=text, field=name, unit=unit))
  names = [column.field for column in columns]
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
    values: dict = {}
    for column, cell in zip(columns, cells):
      cell = cell.strip()
      if not cell:
        continue
      if column.field in measuredColumns:
        try:
          values[column.field] = {"value": float(cell), "unit": column.unit}
        except ValueError as error:
          raise WeatherFileError(f"row {rowNumber}: {column.field} '{cell}' is not a number") from error
      else:
        values[column.field] = cell
    try:
      records.append(WeatherRecord.model_validate(values))
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
  return WeatherFile(records=records, columns=columns)
