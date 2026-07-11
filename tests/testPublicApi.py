# SPDX-License-Identifier: Apache-2.0
"""Tests for the public API surface (A2).

Every import here comes from the top-level `openfurrow` package and nothing else. That
is the point: if the full trial loop can be driven without reaching into
`openfurrow.store`, `openfurrow.design`, `openfurrow.reports`, or any other internal
module, then the public surface is genuinely sufficient and the facade boundary holds.
A future surface (the Flask service, an app) is entitled to exactly this much.

The suite also pins the surface itself -- what is exported, and what is deliberately
not -- so widening or narrowing it is a deliberate act that shows up as a test change.
"""

import csv

import pytest

import openfurrow
from openfurrow import (
  AnovaResult,
  Assumptions,
  ImportResult,
  MeanSeparation,
  Observation,
  RoundTripCheck,
  StoreError,
  TrialDocument,
  TrialLayout,
  TrialPackage,
  Workspace,
  contentHash,
  defaultConfig,
)

_packageDict = {
  "schemaVersion": "0.1.0",
  "trial": {"trialCode": "PUB-1", "title": "Public API trial", "crop": "Barley",
            "season": "2025", "site": "Field A", "objective": "Compare treatments"},
  "treatments": [{"treatmentCode": code, "name": code} for code in ["A", "B", "C", "D"]],
  "design": {"designType": "rcbd", "replications": 3, "randomizationSeed": 7},
  "assessments": [{"assessmentCode": "YIELD", "name": "Yield", "dataType": "numeric",
                   "unit": "kg/ha", "minValue": 0}],
}
_values = {
  ("A", 1): 106, ("A", 2): 99, ("A", 3): 95, ("B", 1): 103, ("B", 2): 100, ("B", 3): 94,
  ("C", 1): 86, ("C", 2): 79, ("C", 3): 75, ("D", 1): 83, ("D", 2): 80, ("D", 3): 74,
}


def testFullLoopThroughPublicSurfaceOnly(tmp_path):
  """Author, import, analyze, report, export, and verify -- public imports only."""
  workspace = Workspace.create(str(tmp_path / "trials.db"))
  package = TrialPackage.model_validate(_packageDict)
  workspace.addPackage(package)
  assert workspace.listTrials() == [("PUB-1", "Public API trial")]

  # The layout is derived through the facade; no direct call to the randomizer.
  layout = workspace.layoutFor("PUB-1")
  assert isinstance(layout, TrialLayout)
  assert len(layout.plots) == package.plotCount

  # Observations, written against the layout the facade handed back.
  csvPath = tmp_path / "obs.csv"
  with csvPath.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.writer(handle)
    writer.writerow(["plotNumber", "assessmentCode", "value"])
    for plot in sorted(layout.plots, key=lambda plot: plot.plotNumber):
      writer.writerow([plot.plotNumber, "YIELD", _values[(plot.treatmentCode, plot.block)]])

  result = workspace.importObservations("PUB-1", str(csvPath), defaultConfig().importProfile)
  assert isinstance(result, ImportResult)
  assert len(result.observations) == package.plotCount
  assert all(isinstance(observation, Observation) for observation in workspace.loadObservations("PUB-1"))

  # Analysis, mean separation, and diagnostics all come back as public result types.
  anova = workspace.analyze("PUB-1", "YIELD")
  assert isinstance(anova, AnovaResult)
  separation = workspace.separateMeans("PUB-1", "YIELD")
  assert isinstance(separation, MeanSeparation)
  assert separation.treatmentSignificant is True
  assert isinstance(workspace.assessAssumptions("PUB-1", "YIELD"), Assumptions)

  report = workspace.buildReport("PUB-1")
  assert "PUB-1" in report

  # Exchange and fixity.
  jsonPath = str(tmp_path / "trial.json")
  workspace.exportDocument("PUB-1", jsonPath)
  check = workspace.verifyRoundTrip("PUB-1")
  assert isinstance(check, RoundTripCheck)
  assert check.matches is True

  # The public contentHash is THE hash -- the facade's and a caller's agree.
  document = TrialDocument(
    package=workspace.loadPackage("PUB-1"),
    observations=workspace.loadObservations("PUB-1"),
  )
  assert contentHash(document) == workspace.contentHashFor("PUB-1")

  # Field Book interop is on the facade too.
  workspace.exportFieldBook("PUB-1", str(tmp_path / "f.csv"), str(tmp_path / "t.trt"))

  workspace.deleteTrial("PUB-1")
  assert workspace.listTrials() == []


def testPublicErrorsAreCatchableFromTheRoot(tmp_path):
  """A caller catches core failures using only the root's error types."""
  with pytest.raises(StoreError):
    Workspace.open(str(tmp_path / "missing.db"))


def testPublicSurfaceIsExported():
  """Names the public API promises are present and listed in __all__."""
  expected = {
    "Workspace", "RoundTripCheck",
    "AnalysisError", "ExchangeError", "ObservationImportError", "StoreError",
    "TrialPackage", "TrialDocument", "TrialLayout", "Observation", "contentHash",
    "AnovaResult", "MeanSeparation", "Assumptions", "ImportResult",
    "ImportProfile", "defaultConfig", "loadConfig", "schemaVersion",
  }
  missing = expected - set(openfurrow.__all__)
  assert missing == set()
  # Everything __all__ promises actually resolves.
  unresolved = [name for name in openfurrow.__all__ if not hasattr(openfurrow, name)]
  assert unresolved == []


def testInternalsAreNotPublic():
  """Internal operations stay behind the facade and are absent from the root."""
  # These are reached through Workspace; exporting them would let a surface bypass
  # the facade and re-implement part of the core.
  internals = [
    "createDatabase", "sessionScope", "savePackage", "saveObservations",
    "generateRcbdLayout", "buildReport", "importObservations",
    "analyzeRcbd", "separateMeans", "assessAssumptions",
    "exportJson", "importJson", "writeFieldImport", "writeTraitFile",
  ]
  exposed = [name for name in internals if name in openfurrow.__all__]
  assert exposed == []
