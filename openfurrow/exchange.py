# SPDX-License-Identifier: Apache-2.0
"""Portable exchange: JSON and CSV import/export for trial documents.

Data ownership means a trial is never trapped in the store. A trial document
exports to a single JSON file -- the portable, human-readable archival artifact,
re-validated on import -- and observations export to long-format CSV annotated with
block and treatment for spreadsheets, R, and pandas. The JSON round-trips to the
same content hash as the database, so an exported file is a faithful, movable copy
of the record, not a lossy dump.
"""

from __future__ import annotations

import csv
import json

from pydantic import ValidationError

from openfurrow.schema.document import TrialDocument


class ExchangeError(ValueError):
  """A file is not a trial document that can be imported."""


def exportJson(document: TrialDocument, path: str) -> None:
  """Write a trial document to a deterministic, human-readable JSON file.

  The bytes are the same on every platform: UTF-8 with LF line endings.
  """
  with open(path, "w", encoding="utf-8", newline="\n") as handle:
    json.dump(document.canonicalDict(), handle, sort_keys=True, indent=2)
    handle.write("\n")


def importJson(path: str) -> TrialDocument:
  """Read and validate a trial document from a JSON file.

  Validation is the schema's: a malformed package (too few treatments, a bad enum,
  an out-of-domain field), a layout that does not fit the package, or an observation
  on a plot the layout does not have is rejected here, not silently accepted.
  """
  with open(path, encoding="utf-8") as handle:
    try:
      data = json.load(handle)
    except json.JSONDecodeError as error:
      raise ExchangeError(f"not valid JSON: {error}") from error
  try:
    return TrialDocument.model_validate(data)
  except ValidationError as error:
    raise ExchangeError(f"not a valid trial document: {error}") from error


def exportObservationsCsv(document: TrialDocument, path: str) -> None:
  """Write observations as long-format CSV, annotated with block and treatment.

  Block and treatment come from the document's layout, giving a file that is
  directly analyzable in a spreadsheet or R. A missing value is written as an
  empty cell.
  """
  plotInfo = {plot.plotNumber: (plot.block, plot.treatmentCode) for plot in document.layout}
  orderedObservations = sorted(document.observations, key=lambda row: (row.plotNumber, row.assessmentCode))

  with open(path, "w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow(["plotNumber", "block", "treatment", "assessmentCode", "value"])
    for observation in orderedObservations:
      block, treatment = plotInfo[observation.plotNumber]
      value = "" if observation.value is None else observation.value
      writer.writerow([observation.plotNumber, block, treatment, observation.assessmentCode, value])
