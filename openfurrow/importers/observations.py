# SPDX-License-Identifier: Apache-2.0
"""Import observations from a CSV into the canonical long-format atom.

Both long and wide files are accepted and converted to a single list of
Observation rows. The import profile declares the file shape and value parsing;
the trial package and layout supply the validation context -- which plots exist,
which assessments are defined, and the value domain of each assessment.

The importer fails loud on anything ambiguous or wrong: an unknown plot or
assessment, a value that cannot be parsed to its assessment's type, a value
outside its domain, a duplicate plot/assessment pair, or a missing required
column. The one non-fatal case is an explicitly missing value (a configured NA
token), which is recorded as a None-valued observation plus a warning rather
than silently dropped.
"""

from __future__ import annotations

import csv
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from openfurrow.config.profile import ImportFormat, ImportProfile
from openfurrow.schema.observation import Observation
from openfurrow.schema.trialPackage import AssessmentDataType, AssessmentDefinition, TrialPackage
from openfurrow.schema.layout import TrialLayout


class ObservationImportError(ValueError):
  """An observation file is malformed or contains invalid data."""


class ImportWarning(BaseModel):
  """A non-fatal note raised during import."""

  model_config = ConfigDict(extra="forbid")

  kind: str
  message: str
  rowNumber: int | None = None
  plotNumber: int | None = None
  assessmentCode: str | None = None


class ImportResult(BaseModel):
  """The outcome of an import: the observations and any warnings."""

  model_config = ConfigDict(extra="forbid")

  observations: list[Observation]
  warnings: list[ImportWarning]


def importObservations(
  csvPath: str | Path,
  package: TrialPackage,
  layout: TrialLayout,
  profile: ImportProfile | None = None,
) -> ImportResult:
  """Read an observation CSV and return validated observations plus warnings."""
  if layout.trialCode != package.trial.trialCode:
    raise ObservationImportError(
      f"layout trialCode '{layout.trialCode}' does not match package trial '{package.trial.trialCode}'"
    )
  profile = profile or ImportProfile()
  assessments = {assessment.assessmentCode: assessment for assessment in package.assessments}
  validPlots = {plot.plotNumber for plot in layout.plots}

  rows, fieldnames = _readRows(csvPath)
  if profile.format is ImportFormat.long:
    parsed = _parseLong(rows, fieldnames, profile, assessments)
  else:
    parsed = _parseWide(rows, fieldnames, profile, assessments)

  observations: list[Observation] = []
  warnings: list[ImportWarning] = []
  seen: set[tuple[int, str]] = set()
  for rowNumber, plotNumber, assessmentCode, rawValue in parsed:
    if plotNumber not in validPlots:
      raise ObservationImportError(
        f"row {rowNumber}: plot {plotNumber} is not in the trial layout"
      )
    key = (plotNumber, assessmentCode)
    if key in seen:
      raise ObservationImportError(
        f"row {rowNumber}: duplicate observation for plot {plotNumber} assessment '{assessmentCode}'"
      )
    seen.add(key)

    value, warning = _parseValue(
      rawValue, assessments[assessmentCode], profile, rowNumber, plotNumber
    )
    observations.append(
      Observation(plotNumber=plotNumber, assessmentCode=assessmentCode, value=value)
    )
    if warning is not None:
      warnings.append(warning)

  return ImportResult(observations=observations, warnings=warnings)


def _readRows(csvPath: str | Path) -> tuple[list[dict[str, str]], list[str]]:
  with Path(csvPath).open(newline="", encoding="utf-8") as handle:
    reader = csv.DictReader(handle)
    fieldnames = reader.fieldnames
    if not fieldnames:
      raise ObservationImportError("CSV has no header row")
    rows = list(reader)
  return rows, list(fieldnames)


def _requireColumns(fieldnames: list[str], needed: list[str], role: str) -> None:
  missing = [column for column in needed if column not in fieldnames]
  if missing:
    raise ObservationImportError(f"{role} column(s) not found in CSV header: {missing}")


def _parseLong(rows, fieldnames, profile, assessments):
  columns = profile.long
  _requireColumns(fieldnames, [columns.plotNumber, columns.assessmentCode, columns.value], "long-format")
  parsed = []
  for rowNumber, row in enumerate(rows, start=2):
    plotNumber = _parsePlotNumber(row[columns.plotNumber], rowNumber)
    assessmentCode = (row[columns.assessmentCode] or "").strip()
    if assessmentCode not in assessments:
      raise ObservationImportError(
        f"row {rowNumber}: assessment '{assessmentCode}' is not defined in the trial package"
      )
    parsed.append((rowNumber, plotNumber, assessmentCode, row[columns.value]))
  return parsed


def _parseWide(rows, fieldnames, profile, assessments):
  columns = profile.wide
  _requireColumns(fieldnames, [columns.plotNumber], "wide-format plot")
  ignored = set(columns.ignoreColumns)
  if columns.assessmentColumns is not None:
    _requireColumns(fieldnames, columns.assessmentColumns, "wide-format assessment")
    assessmentColumns = columns.assessmentColumns
  else:
    assessmentColumns = [
      column for column in fieldnames if column != columns.plotNumber and column not in ignored
    ]
  unknown = [column for column in assessmentColumns if column not in assessments]
  if unknown:
    raise ObservationImportError(
      f"wide-format assessment column(s) not defined in the trial package: {unknown}"
    )

  parsed = []
  for rowNumber, row in enumerate(rows, start=2):
    plotNumber = _parsePlotNumber(row[columns.plotNumber], rowNumber)
    for assessmentColumn in assessmentColumns:
      parsed.append((rowNumber, plotNumber, assessmentColumn, row[assessmentColumn]))
  return parsed


def _parsePlotNumber(rawText: str, rowNumber: int) -> int:
  text = (rawText or "").strip()
  try:
    return int(text)
  except ValueError as error:
    raise ObservationImportError(
      f"row {rowNumber}: plot number '{rawText}' is not an integer"
    ) from error


def _parseValue(
  rawText: str,
  assessment: AssessmentDefinition,
  profile: ImportProfile,
  rowNumber: int,
  plotNumber: int,
) -> tuple[float | str | None, ImportWarning | None]:
  text = (rawText or "").strip()
  if text in profile.parsing.naTokens:
    warning = ImportWarning(
      kind="missingValue",
      message=f"plot {plotNumber} assessment '{assessment.assessmentCode}': value treated as missing",
      rowNumber=rowNumber,
      plotNumber=plotNumber,
      assessmentCode=assessment.assessmentCode,
    )
    return None, warning

  if assessment.dataType is AssessmentDataType.numeric:
    return _parseNumeric(text, assessment, profile, rowNumber), None
  return _parseCategorical(text, assessment, rowNumber), None


def _parseNumeric(text, assessment, profile, rowNumber):
  separator = profile.parsing.decimalSeparator
  normalized = text.replace(separator, ".") if separator != "." else text
  try:
    value = float(normalized)
  except ValueError as error:
    raise ObservationImportError(
      f"row {rowNumber}: value '{text}' for numeric assessment "
      f"'{assessment.assessmentCode}' is not a number"
    ) from error
  if assessment.minValue is not None and value < assessment.minValue:
    raise ObservationImportError(
      f"row {rowNumber}: value {value} for assessment '{assessment.assessmentCode}' "
      f"is below the minimum {assessment.minValue}"
    )
  if assessment.maxValue is not None and value > assessment.maxValue:
    raise ObservationImportError(
      f"row {rowNumber}: value {value} for assessment '{assessment.assessmentCode}' "
      f"is above the maximum {assessment.maxValue}"
    )
  return value


def _parseCategorical(text, assessment, rowNumber):
  if assessment.allowedValues is None or text not in assessment.allowedValues:
    raise ObservationImportError(
      f"row {rowNumber}: value '{text}' for assessment '{assessment.assessmentCode}' "
      f"is not one of {assessment.allowedValues}"
    )
  return text
