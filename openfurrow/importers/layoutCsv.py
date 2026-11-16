# SPDX-License-Identifier: Apache-2.0
"""A field layout as planted, read from a CSV file (decision 0015, worklist USR-7).

The file has one row per plot with the columns plotNumber, block, positionInBlock and
treatmentCode, in any order; other columns (rows, ranges, notes) are left aside. Every
value must be there and whole numbers must be whole numbers: the layout is kept exactly
as given, so nothing in it is guessed.
"""

from __future__ import annotations

import csv
from pathlib import Path

from openfurrow.schema.layout import PlotAssignment

layoutColumns = ("plotNumber", "block", "positionInBlock", "treatmentCode")


class LayoutFileError(ValueError):
  """A layout file that cannot be read as plots."""


def readLayoutCsv(path: str | Path) -> list[PlotAssignment]:
  """The plots a layout CSV lists, in file order. Raises LayoutFileError naming the row."""
  with open(path, encoding="utf-8-sig", newline="") as handle:
    reader = csv.DictReader(handle)
    missing = [column for column in layoutColumns if column not in (reader.fieldnames or [])]
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
  return plots
