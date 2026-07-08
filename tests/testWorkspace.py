# SPDX-License-Identifier: Apache-2.0
"""Tests for the core facade (`openfurrow.workspace.Workspace`).

The facade is the single surface every non-core caller uses, so these tests drive
the whole trial loop through it: create/open, add, list, load, layout, import,
analyze, separate means, assess assumptions, report, export/import, hash, verify,
delete. Composite operations are cross-checked against the underlying primitives to
prove the facade delegates faithfully -- it must return exactly what a direct call
to the core function would, never a re-derived approximation. The fail-loud paths
(open a missing database, load an unknown trial, analyze before data exists) must
raise the declared error types.
"""

import csv
import json
from pathlib import Path

import pytest

from openfurrow.analysis import analyzeRcbd, assessAssumptions, separateMeans
from openfurrow.config import defaultConfig
from openfurrow.design import generateRcbdLayout
from openfurrow.reports import buildReport
from openfurrow.schema import TrialDocument, TrialPackage, contentHash
from openfurrow.workspace import (
  AnalysisError,
  RoundTripCheck,
  StoreError,
  Workspace,
)

_packageDict = {
  "schemaVersion": "0.1.0",
  "trial": {"trialCode": "WS-1", "title": "Facade trial", "crop": "Barley", "season": "2025",
            "site": "Field A", "objective": "Compare treatments"},
  "treatments": [{"treatmentCode": code, "name": code} for code in ["A", "B", "C", "D"]],
  "design": {"designType": "rcbd", "replications": 3, "randomizationSeed": 7},
  "assessments": [{"assessmentCode": "YIELD", "name": "Yield", "dataType": "numeric",
                   "unit": "kg/ha", "minValue": 0}],
}
# Clear treatment separation so the ANOVA is significant and mean separation splits.
_values = {
  ("A", 1): 106, ("A", 2): 99, ("A", 3): 95, ("B", 1): 103, ("B", 2): 100, ("B", 3): 94,
  ("C", 1): 86, ("C", 2): 79, ("C", 3): 75, ("D", 1): 83, ("D", 2): 80, ("D", 3): 74,
}


@pytest.fixture
def trial(tmp_path):
  """Paths and the parsed package for the facade loop; CSV written from the layout."""
  package = TrialPackage.model_validate(_packageDict)
  layout = generateRcbdLayout(package)
  csvPath = tmp_path / "obs.csv"
  with csvPath.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.writer(handle)
    writer.writerow(["plotNumber", "assessmentCode", "value"])
    for plot in sorted(layout.plots, key=lambda plot: plot.plotNumber):
      writer.writerow([plot.plotNumber, "YIELD", _values[(plot.treatmentCode, plot.block)]])
  return {
    "db": str(tmp_path / "trials.db"),
    "db2": str(tmp_path / "copy.db"),
    "csv": str(csvPath),
    "package": package,
    "dir": tmp_path,
  }


def _populated(trial):
  """A workspace with the trial added and its observations imported."""
  workspace = Workspace.create(trial["db"])
  workspace.addPackage(trial["package"])
  workspace.importObservations("WS-1", trial["csv"], defaultConfig().importProfile)
  return workspace


# ---- construction ---------------------------------------------------------

def testCreateMakesUsableStore(trial):
  workspace = Workspace.create(trial["db"])
  assert Path(trial["db"]).exists()
  assert workspace.listTrials() == []


def testOpenMissingDatabaseRaises(trial):
  with pytest.raises(StoreError):
    Workspace.open(trial["db"])


def testOpenExistingReusesData(trial):
  Workspace.create(trial["db"]).addPackage(trial["package"])
  reopened = Workspace.open(trial["db"])
  assert reopened.listTrials() == [("WS-1", "Facade trial")]


# ---- trial management -----------------------------------------------------

def testAddThenListAndLoad(trial):
  workspace = Workspace.create(trial["db"])
  workspace.addPackage(trial["package"])
  assert workspace.listTrials() == [("WS-1", "Facade trial")]
  assert workspace.loadPackage("WS-1") == trial["package"]


def testLoadUnknownTrialRaises(trial):
  workspace = Workspace.create(trial["db"])
  with pytest.raises(StoreError):
    workspace.loadPackage("NOPE")


def testDeleteRemovesTrial(trial):
  workspace = _populated(trial)
  workspace.deleteTrial("WS-1")
  assert workspace.listTrials() == []
  with pytest.raises(StoreError):
    workspace.loadPackage("WS-1")


# ---- layout ---------------------------------------------------------------

def testLayoutMatchesDirectRegeneration(trial):
  workspace = Workspace.create(trial["db"])
  workspace.addPackage(trial["package"])
  assert workspace.layoutFor("WS-1") == generateRcbdLayout(trial["package"])
  assert len(workspace.layoutFor("WS-1").plots) == trial["package"].plotCount


# ---- observations ---------------------------------------------------------

def testImportSavesEveryObservation(trial):
  workspace = Workspace.create(trial["db"])
  workspace.addPackage(trial["package"])
  result = workspace.importObservations("WS-1", trial["csv"], defaultConfig().importProfile)
  assert len(result.observations) == trial["package"].plotCount
  assert len(workspace.loadObservations("WS-1")) == trial["package"].plotCount


def testAnalyzeBeforeImportRaises(trial):
  workspace = Workspace.create(trial["db"])
  workspace.addPackage(trial["package"])
  with pytest.raises(AnalysisError):
    workspace.analyze("WS-1", "YIELD")


# ---- analysis (facade delegates faithfully to the primitives) -------------

def testAnalyzeMatchesPrimitive(trial):
  workspace = _populated(trial)
  package = workspace.loadPackage("WS-1")
  layout = workspace.layoutFor("WS-1")
  observations = workspace.loadObservations("WS-1")
  expected = analyzeRcbd("YIELD", package, layout, observations)
  assert workspace.analyze("WS-1", "YIELD") == expected


def testSeparateMeansMatchesPrimitive(trial):
  workspace = _populated(trial)
  result = workspace.analyze("WS-1", "YIELD")
  expected = separateMeans(result, significanceLevel=0.05, protected=True)
  assert workspace.separateMeans("WS-1", "YIELD") == expected
  # The designed separation is significant, so groups are not all one letter.
  assert expected.treatmentSignificant is True
  assert len({group.group for group in expected.groups}) > 1


def testAssessAssumptionsMatchesPrimitive(trial):
  workspace = _populated(trial)
  package = workspace.loadPackage("WS-1")
  layout = workspace.layoutFor("WS-1")
  observations = workspace.loadObservations("WS-1")
  expected = assessAssumptions("YIELD", package, layout, observations, 0.05)
  assert workspace.assessAssumptions("WS-1", "YIELD") == expected


def testReportMatchesPrimitive(trial):
  workspace = _populated(trial)
  package = workspace.loadPackage("WS-1")
  layout = workspace.layoutFor("WS-1")
  observations = workspace.loadObservations("WS-1")
  expected = buildReport(package, layout, observations, significanceLevel=0.05, protected=True)
  assert workspace.buildReport("WS-1") == expected


# ---- exchange, hashing, verification --------------------------------------

def testContentHashMatchesDocumentHash(trial):
  workspace = _populated(trial)
  document = TrialDocument(
    package=workspace.loadPackage("WS-1"),
    observations=workspace.loadObservations("WS-1"),
  )
  assert workspace.contentHashFor("WS-1") == contentHash(document)


def testExportImportRoundTripPreservesHash(trial):
  source = _populated(trial)
  jsonPath = str(trial["dir"] / "export.json")
  source.exportDocument("WS-1", jsonPath)

  destination = Workspace.create(trial["db2"])
  trialCode = destination.importDocument(jsonPath)
  assert trialCode == "WS-1"
  assert destination.contentHashFor("WS-1") == source.contentHashFor("WS-1")


def testExportObservationsCsvWritesEveryRow(trial):
  workspace = _populated(trial)
  csvPath = str(trial["dir"] / "out.csv")
  workspace.exportObservationsCsv("WS-1", csvPath)
  with open(csvPath, encoding="utf-8") as handle:
    rows = list(csv.reader(handle))
  assert rows[0] == ["plotNumber", "block", "treatment", "assessmentCode", "value"]
  assert len(rows) - 1 == trial["package"].plotCount


def testVerifyRoundTripPasses(trial):
  workspace = _populated(trial)
  check = workspace.verifyRoundTrip("WS-1")
  assert isinstance(check, RoundTripCheck)
  assert check.matches is True
  assert check.storedHash == check.roundTripHash
