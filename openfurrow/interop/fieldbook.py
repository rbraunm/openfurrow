# SPDX-License-Identifier: Apache-2.0
"""Field Book (PhenoApps) file interop -- format-based round-trip.

Field Book is an Android app that replaces the paper field book: you import a field
layout and a trait list, walk the field entering trait values per plot, then export
the collected data. OpenFurrow interoperates by file: it produces the two files
Field Book imports (a field-import CSV and a legacy `.trt` trait list) and ingests
the data export Field Book produces (the database, long, format). Formats follow
`roadmap/research/fieldbook-formats.md`, pinned against Field Book 5.4 and the
current PhenoApps/Field-Book source.

Export is what OpenFurrow legitimately produces; ingest is what it legitimately
consumes. The ingest path reuses the standard observation importer with a Field Book
column mapping (`fieldBookImportProfile`) rather than a parallel reader.

Unique id: the field-import file uses `plotNumber` as Field Book's unique identifier.
Field Book requires it unique across all of a device's fields; within one trial the
plot number is unique, which is the round-trip case. A trial-qualified id would be
needed for many trials sharing a device -- deferred (see the E1 open items).
"""

from __future__ import annotations

import csv
from pathlib import Path

from openfurrow.config.profile import ImportFormat, ImportProfile
from openfurrow.schema.trialPackage import AssessmentDataType, AssessmentDefinition, TrialPackage
from openfurrow.schema.layout import TrialLayout

# Field-import column roles. plotNumber is Field Book's unique id; block and
# positionInBlock are the primary/secondary walk order; treatment rides along as an
# attribute (echoed back on export, ignored on ingest).
fieldUniqueIDColumn = "plotNumber"
fieldPrimaryColumn = "block"
fieldSecondaryColumn = "positionInBlock"
fieldTreatmentColumn = "treatment"

# Database (long) export columns we map on ingest. The trait name we write into the
# `.trt` is the assessment code, so the export's `trait` column round-trips straight
# back to the assessment code.
fieldBookTraitColumn = "trait"
fieldBookValueColumn = "value"

# Legacy .trt header (quoted CSV), in Field Book's column order.
_traitHeader = [
  "trait", "format", "defaultValue", "minimum", "maximum",
  "details", "categories", "isVisible", "realPosition",
]

# Characters Field Book forbids in field-file column headers and file names.
_forbiddenHeaderChars = set('/?<>\\*|"')


def writeFieldImport(package: TrialPackage, layout: TrialLayout, path: str | Path) -> None:
  """Write the Field Book field-import CSV: one row per plot, ordered by plot number.

  Columns are plotNumber (unique id), block (primary order), positionInBlock
  (secondary order), and treatment (a carried attribute).
  """
  header = [fieldUniqueIDColumn, fieldPrimaryColumn, fieldSecondaryColumn, fieldTreatmentColumn]
  _rejectForbiddenHeaders(header)
  with open(path, "w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow(header)
    for plot in sorted(layout.plots, key=lambda plot: plot.plotNumber):
      writer.writerow([plot.plotNumber, plot.block, plot.positionInBlock, plot.treatmentCode])


def writeTraitFile(package: TrialPackage, path: str | Path) -> None:
  """Write the legacy `.trt` trait list: one fully-quoted row per assessment.

  Each assessment becomes a Field Book trait whose name is the assessment code (so
  the collected export's `trait` column maps straight back). Numeric assessments
  export as the numeric format with their unit and bounds; categorical and ordinal
  assessments export as categorical with their allowed values slash-joined.
  """
  with open(path, "w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle, quoting=csv.QUOTE_ALL)
    writer.writerow(_traitHeader)
    for position, assessment in enumerate(package.assessments, start=1):
      writer.writerow(_traitRow(assessment, position))


def fieldBookImportProfile() -> ImportProfile:
  """The import profile mapping a Field Book database (long) export onto observations.

  Long format: the unique-id column is the plot, `trait` the assessment code, `value`
  the value. Every other export column (timestamp, person, location, device_name, the
  attachment columns) is unmapped and ignored by the importer.
  """
  return ImportProfile(
    format=ImportFormat.long,
    long={
      "plotNumber": fieldUniqueIDColumn,
      "assessmentCode": fieldBookTraitColumn,
      "value": fieldBookValueColumn,
    },
  )


def _traitRow(assessment: AssessmentDefinition, position: int) -> list[str]:
  numeric = assessment.dataType is AssessmentDataType.numeric
  traitFormat = "numeric" if numeric else "categorical"
  minimum = _number(assessment.minValue) if numeric else ""
  maximum = _number(assessment.maxValue) if numeric else ""
  details = (assessment.unit or assessment.name) if numeric else assessment.name
  categories = "/".join(assessment.allowedValues) if assessment.allowedValues else ""
  return [
    assessment.assessmentCode, traitFormat, "", minimum, maximum,
    details, categories, "true", str(position),
  ]


def _number(value: float | None) -> str:
  """Render a bound without a trailing '.0' for whole numbers, '' for None."""
  if value is None:
    return ""
  return str(int(value)) if float(value).is_integer() else str(value)


def _rejectForbiddenHeaders(header: list[str]) -> None:
  for column in header:
    bad = _forbiddenHeaderChars & set(column)
    if bad:
      raise ValueError(
        f"field-import column '{column}' contains characters Field Book forbids: {sorted(bad)}"
      )
