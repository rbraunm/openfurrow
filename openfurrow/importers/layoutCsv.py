# SPDX-License-Identifier: Apache-2.0
"""A field layout as planted, read from a CSV file (decision 0015, worklist USR-7).

The file has one row per plot with the columns plotNumber, block, positionInBlock and
treatmentCode, in any order; other columns (rows, ranges, notes) are left aside. Every
value must be there and whole numbers must be whole numbers: the layout is kept exactly
as given, so nothing in it is guessed. The file is read from its bytes, the form an import
keeps it in (decision 0044).
"""

from __future__ import annotations

import csv
import io

from pydantic import BaseModel, ConfigDict

from openfurrow.schema.layout import PlotAssignment

layoutColumns = ("plotNumber", "block", "positionInBlock", "treatmentCode")


class LayoutFileError(ValueError):
  """A layout file that cannot be read as plots."""


class LayoutFile(BaseModel):
  """The plots a layout file lists, in file order, and the columns it has that a layout does not read."""

  model_config = ConfigDict(extra="forbid")

  plots: list[PlotAssignment]
  unreadColumns: list[str]


def readLayoutCsv(data: bytes) -> LayoutFile:
  """The plots a layout CSV lists. Raises LayoutFileError naming the row."""
  try:
    text = data.decode("utf-8-sig")
  except UnicodeDecodeError as error:
    raise LayoutFileError(f"the layout file is not UTF-8 text (byte {error.start}); save it as CSV UTF-8") from error
  reader = csv.DictReader(io.StringIO(text, newline=""))
  header = reader.fieldnames or []
  missing = [column for column in layoutColumns if column not in header]
  if missing:
    raise LayoutFileError(f"the layout file lacks the column(s) {missing}; it needs {list(layoutColumns)}")
  plots = []
  for rowNumber, row in enumerate(reader, start=2):
    try:
      numbers = {column: int(row[column].strip()) for column in layoutColumns[:3]}
    except (ValueError, AttributeError) as error:
      raise LayoutFileError(f"row {rowNumber}: plotNumber, block and positionInBlock are whole numbers") from error
    treatmentCode = (row["treatmentCode"] or "").strip()
    if not treatmentCode:
      raise LayoutFileError(f"row {rowNumber}: treatmentCode is empty")
    plots.append(PlotAssignment(treatmentCode=treatmentCode, **numbers))
  if not plots:
    raise LayoutFileError("the layout file lists no plots")
  return LayoutFile(plots=plots, unreadColumns=[column for column in header if column not in layoutColumns])
