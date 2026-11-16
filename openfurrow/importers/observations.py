# SPDX-License-Identifier: Apache-2.0
"""Import observations from a CSV or a workbook into the canonical long-format atom.

The file is read into a table first (decision 0031), so a CSV and an .xlsx sheet are
imported alike. Both long and wide tables are accepted and converted to a single list
of Observation rows. The import profile declares the file shape and value parsing;
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

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from openfurrow.config.profile import ImportFormat, ImportProfile
from openfurrow.importers.spreadsheet import SheetTable, SpreadsheetError, readTable
from openfurrow.schema.observation import Observation
from openfurrow.schema.assessment import AssessmentDataType, Rating
from openfurrow.schema.trialPackage import TrialPackage
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


class AssessmentCount(BaseModel):
  """How one assessment came out of an import, against the plots of the trial."""

  model_config = ConfigDict(extra="forbid")

  assessmentCode: str
  values: int
  missing: int
  plotsWithout: list[int]


def countByAssessment(result: ImportResult, layout: TrialLayout) -> list[AssessmentCount]:
  """Each imported assessment's values, its marked-missing values, and the plots the file left out."""
  plots = sorted({plot.plotNumber for plot in layout.plots} | {check.plotNumber for check in layout.checkPlots})
  codes = list(dict.fromkeys(observation.assessmentCode for observation in result.observations))
  counts = []
  for code in codes:
    given = [observation for observation in result.observations if observation.assessmentCode == code]
    present = {observation.plotNumber for observation in given}
    counts.append(AssessmentCount(
      assessmentCode=code,
      values=sum(observation.value is not None for observation in given),
      missing=sum(observation.value is None for observation in given),
      plotsWithout=[number for number in plots if number not in present],
    ))
  return counts


def importObservations(
  path: str | Path,
  package: TrialPackage,
  layout: TrialLayout,
  profile: ImportProfile | None = None,
  sheetName: str | None = None,
) -> ImportResult:
  """Read an observation .csv or .xlsx file and return validated observations plus warnings."""
  path = Path(path)
  try:
    table = readTable(path.name, path.read_bytes(), sheetName)
  except SpreadsheetError as error:
    raise ObservationImportError(str(error)) from error
  return importTable(table, package, layout, profile)


def importTable(
  table: SheetTable,
  package: TrialPackage,
  layout: TrialLayout,
  profile: ImportProfile | None = None,
) -> ImportResult:
  """Validate a table's observations against the trial and return them plus warnings."""
  if layout.trialCode != package.trial.trialCode:
    raise ObservationImportError(
      f"layout trialCode '{layout.trialCode}' does not match package trial '{package.trial.trialCode}'"
    )
  profile = profile or ImportProfile()
  assessments = {
    assessment.assessmentCode: package.ratingFor(assessment.assessmentCode)
    for assessment in package.assessments
  }
  validPlots = {plot.plotNumber for plot in layout.plots} | {check.plotNumber for check in layout.checkPlots}

  rows = [
    (rowNumber, dict(zip(table.header, cells))) for rowNumber, cells in zip(table.rowNumbers, table.rows)
  ]
  fieldnames = table.header
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
      rawValue, assessmentCode, assessments[assessmentCode], profile, rowNumber, plotNumber
    )
    observations.append(
      Observation(plotNumber=plotNumber, assessmentCode=assessmentCode, value=value)
    )
    if warning is not None:
      warnings.append(warning)

  return ImportResult(observations=observations, warnings=warnings)


def _requireColumns(fieldnames: list[str], needed: list[str], role: str) -> None:
  missing = [column for column in needed if column not in fieldnames]
  if missing:
    raise ObservationImportError(f"{role} column(s) not found in the header: {missing}")


def _parseLong(rows, fieldnames, profile, assessments):
  columns = profile.long
  _requireColumns(fieldnames, [columns.plotNumber, columns.assessmentCode, columns.value], "long-format")
  parsed = []
  for rowNumber, row in rows:
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
    _requireColumns(fieldnames, list(columns.assessmentColumns), "wide-format assessment")
    assessmentColumns = columns.assessmentColumns
  else:
    assessmentColumns = {
      column: column for column in fieldnames if column != columns.plotNumber and column not in ignored
    }
  unknown = sorted(code for code in assessmentColumns.values() if code not in assessments)
  if unknown:
    raise ObservationImportError(
      f"wide-format assessment(s) not defined in the trial package: {unknown}"
    )

  parsed = []
  for rowNumber, row in rows:
    plotNumber = _parsePlotNumber(row[columns.plotNumber], rowNumber)
    for column, assessmentCode in assessmentColumns.items():
      parsed.append((rowNumber, plotNumber, assessmentCode, row[column]))
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
  assessmentCode: str,
  rating: Rating,
  profile: ImportProfile,
  rowNumber: int,
  plotNumber: int,
) -> tuple[float | str | None, ImportWarning | None]:
  text = (rawText or "").strip()
  if text in profile.parsing.naTokens:
    warning = ImportWarning(
      kind="missingValue",
      message=f"plot {plotNumber} assessment '{assessmentCode}': value treated as missing",
      rowNumber=rowNumber,
      plotNumber=plotNumber,
      assessmentCode=assessmentCode,
    )
    return None, warning

  if rating.dataType is AssessmentDataType.numeric:
    return _parseNumeric(text, assessmentCode, rating, profile, rowNumber), None
  return _parseCategorical(text, assessmentCode, rating, rowNumber), None


def _parseNumeric(text, assessmentCode, rating, profile, rowNumber):
  separator = profile.parsing.decimalSeparator
  normalized = text.replace(separator, ".") if separator != "." else text
  try:
    value = float(normalized)
  except ValueError as error:
    raise ObservationImportError(
      f"row {rowNumber}: value '{text}' for numeric assessment "
      f"'{assessmentCode}' is not a number"
    ) from error
  if rating.minValue is not None and value < rating.minValue:
    raise ObservationImportError(
      f"row {rowNumber}: value {value} for assessment '{assessmentCode}' "
      f"is below the minimum {rating.minValue}"
    )
  if rating.maxValue is not None and value > rating.maxValue:
    raise ObservationImportError(
      f"row {rowNumber}: value {value} for assessment '{assessmentCode}' "
      f"is above the maximum {rating.maxValue}"
    )
  return value


def _parseCategorical(text, assessmentCode, rating, rowNumber):
  if rating.allowedValues is None or text not in rating.allowedValues:
    raise ObservationImportError(
      f"row {rowNumber}: value '{text}' for assessment '{assessmentCode}' "
      f"is not one of {rating.allowedValues}"
    )
  return text
