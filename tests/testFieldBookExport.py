# SPDX-License-Identifier: Apache-2.0
"""Tests for Field Book export (E1a): the field-import CSV and the legacy .trt file.

The files must match the formats pinned in roadmap/research/fieldbook-formats.md: the
field import carries plotNumber/block/positionInBlock/treatment with one row per plot,
and the trait file is a fully-quoted CSV whose columns and per-trait mapping follow
Field Book's legacy .trt (numeric -> numeric with unit and bounds; ordinal/categorical
-> categorical with slash-joined values). The trait name is the assessment code so the
collected export round-trips. Forbidden field-header characters fail loud.
"""

import csv
from pathlib import Path

import pytest

from openfurrow.design import generateRcbdLayout
from openfurrow.interop.fieldbook import (
  _rejectForbiddenHeaders,
  _traitHeader,
  writeFieldImport,
  writeTraitFile,
)
from openfurrow.schema import TrialPackage
from openfurrow.workspace import Workspace

_packageDict = {
  "schemaVersion": "0.1.0",
  "trial": {"trialCode": "FB-1", "title": "Field Book export", "crop": "Barley", "season": "2025",
            "site": "Field A", "objective": "Compare treatments"},
  "treatments": [{"treatmentCode": code, "name": code} for code in ["A", "B", "C", "D"]],
  "design": {"designType": "rcbd", "replications": 3, "randomizationSeed": 7},
  "assessments": [
    {"assessmentCode": "YIELD", "name": "Grain yield", "dataType": "numeric",
     "unit": "kg/ha", "minValue": 0, "maxValue": 200},
    {"assessmentCode": "SEV", "name": "Disease severity", "dataType": "ordinal",
     "allowedValues": ["none", "low", "moderate", "high"]},
  ],
}


@pytest.fixture
def package():
  return TrialPackage.model_validate(_packageDict)


def _readCsv(path):
  with open(path, encoding="utf-8") as handle:
    return list(csv.reader(handle))


# ---- field import ---------------------------------------------------------

def testFieldImportHeaderAndRowCount(package, tmp_path):
  path = tmp_path / "field.csv"
  writeFieldImport(package, generateRcbdLayout(package), path)
  rows = _readCsv(path)
  assert rows[0] == ["plotNumber", "block", "positionInBlock", "treatment"]
  assert len(rows) - 1 == package.plotCount


def testFieldImportRowsCoverEveryPlotOrdered(package, tmp_path):
  path = tmp_path / "field.csv"
  layout = generateRcbdLayout(package)
  writeFieldImport(package, layout, path)
  body = _readCsv(path)[1:]
  plotNumbers = [int(row[0]) for row in body]
  assert plotNumbers == sorted(plotNumbers)
  assert set(plotNumbers) == {plot.plotNumber for plot in layout.plots}
  # Every row's treatment is one of the defined treatment codes.
  codes = {treatment.treatmentCode for treatment in package.treatments}
  assert all(row[3] in codes for row in body)


def testFieldImportRowMatchesLayout(package, tmp_path):
  path = tmp_path / "field.csv"
  layout = generateRcbdLayout(package)
  writeFieldImport(package, layout, path)
  byPlot = {plot.plotNumber: plot for plot in layout.plots}
  for row in _readCsv(path)[1:]:
    plot = byPlot[int(row[0])]
    assert [int(row[1]), int(row[2]), row[3]] == [plot.block, plot.positionInBlock, plot.treatmentCode]


def testForbiddenFieldHeaderFailsLoud():
  with pytest.raises(ValueError):
    _rejectForbiddenHeaders(["plot/number"])


# ---- trait file -----------------------------------------------------------

def testTraitFileHeaderAndOneRowPerAssessment(package, tmp_path):
  path = tmp_path / "traits.trt"
  writeTraitFile(package, path)
  rows = _readCsv(path)
  assert rows[0] == _traitHeader
  assert len(rows) - 1 == len(package.assessments)


def testNumericTraitRow(package, tmp_path):
  path = tmp_path / "traits.trt"
  writeTraitFile(package, path)
  yieldRow = next(row for row in _readCsv(path)[1:] if row[0] == "YIELD")
  # trait, format, defaultValue, minimum, maximum, details, categories, isVisible, realPosition
  assert yieldRow == ["YIELD", "numeric", "", "0", "200", "kg/ha", "", "true", "1"]


def testCategoricalTraitRow(package, tmp_path):
  path = tmp_path / "traits.trt"
  writeTraitFile(package, path)
  sevRow = next(row for row in _readCsv(path)[1:] if row[0] == "SEV")
  assert sevRow == ["SEV", "categorical", "", "", "", "Disease severity",
                    "none/low/moderate/high", "true", "2"]


def testTraitFileIsFullyQuoted(package, tmp_path):
  path = tmp_path / "traits.trt"
  writeTraitFile(package, path)
  firstLine = Path(path).read_text(encoding="utf-8").splitlines()[0]
  assert firstLine.startswith('"trait"')


# ---- via the facade -------------------------------------------------------

def testFacadeExportWritesBothFiles(package, tmp_path):
  workspace = Workspace.create(str(tmp_path / "trials.db"))
  workspace.addPackage(package)
  fieldPath = tmp_path / "f.csv"
  traitPath = tmp_path / "t.trt"
  workspace.exportFieldBook("FB-1", str(fieldPath), str(traitPath))
  # Facade output matches the direct writers.
  directField = tmp_path / "f_direct.csv"
  directTrait = tmp_path / "t_direct.trt"
  writeFieldImport(package, generateRcbdLayout(package), directField)
  writeTraitFile(package, directTrait)
  assert fieldPath.read_text(encoding="utf-8") == directField.read_text(encoding="utf-8")
  assert traitPath.read_text(encoding="utf-8") == directTrait.read_text(encoding="utf-8")
