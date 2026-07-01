# SPDX-License-Identifier: Apache-2.0
"""Tests for portable exchange (JSON and CSV).

The central guarantee is that a trial is never trapped in the store: the database
and a JSON export agree on the content hash, so the exported file is a faithful,
movable copy. JSON export is deterministic and its import is validated; the CSV
export carries the layout (block and treatment) and represents missing values as
empty cells.
"""

import csv
from pathlib import Path

import pytest
from pydantic import ValidationError

from openfurrow.design import generateRcbdLayout
from openfurrow.exchange import ExchangeError, exportJson, exportObservationsCsv, importJson
from openfurrow.schema import TrialDocument, TrialPackage, contentHash
from openfurrow.schema.observation import Observation
from openfurrow.store import (
  createDatabase,
  loadObservations,
  loadPackage,
  savePackage,
  saveObservations,
  sessionScope,
)


def samplePackage(trialCode="TRIAL-1"):
  return TrialPackage.model_validate({
    "schemaVersion": "0.1.0",
    "trial": {"trialCode": trialCode, "title": "Sample trial", "crop": "Wheat", "season": "2025",
              "site": "Field A", "objective": "Compare fungicides", "investigator": "Dr. X"},
    "treatments": [
      {"treatmentCode": "T1", "name": "Untreated control"},
      {"treatmentCode": "T2", "name": "Fungicide X", "product": "Prod X", "rate": 2.5, "rateUnit": "L/ha"},
      {"treatmentCode": "T3", "name": "Fungicide Y", "product": "Prod Y", "rate": 1.0, "rateUnit": "kg/ha"},
    ],
    "design": {"designType": "rcbd", "replications": 4, "randomizationSeed": 42},
    "assessments": [
      {"assessmentCode": "YIELD", "name": "Grain yield", "dataType": "numeric", "unit": "kg/ha", "minValue": 0},
      {"assessmentCode": "LODGE", "name": "Lodging", "dataType": "ordinal",
       "allowedValues": ["none", "slight", "severe"]},
    ],
  })


def sampleDocument(package=None):
  package = package or samplePackage()
  layout = generateRcbdLayout(package)
  observations = []
  for index, plot in enumerate(layout.plots):
    observations.append(Observation(plotNumber=plot.plotNumber, assessmentCode="YIELD", value=100.0 + index * 1.25))
    observations.append(Observation(plotNumber=plot.plotNumber, assessmentCode="LODGE", value="none"))
  observations[0] = Observation(plotNumber=observations[0].plotNumber, assessmentCode="YIELD", value=None)
  return TrialDocument(package=package, observations=observations)


# ---- JSON round trip ------------------------------------------------------

def testJsonRoundTripPreservesHashAndEquality(tmp_path):
  document = sampleDocument()
  path = str(tmp_path / "trial.json")
  exportJson(document, path)
  imported = importJson(path)
  # canonical export sorts observations, so compare by content, not list order
  key = lambda observation: (observation.plotNumber, observation.assessmentCode)
  assert imported.package == document.package
  assert sorted(imported.observations, key=key) == sorted(document.observations, key=key)
  assert contentHash(imported) == contentHash(document)


def testJsonExportIsDeterministic(tmp_path):
  document = sampleDocument()
  first = tmp_path / "a.json"
  second = tmp_path / "b.json"
  exportJson(document, str(first))
  exportJson(document, str(second))
  assert first.read_bytes() == second.read_bytes()


def testDatabaseAndJsonAgreeOnHash(tmp_path):
  # The ownership guarantee: the store and a JSON export describe the same trial.
  document = sampleDocument()
  engine = createDatabase(str(tmp_path / "trials.db"))
  with sessionScope(engine) as session:
    savePackage(session, document.package)
    saveObservations(session, "TRIAL-1", document.observations)
  with sessionScope(engine) as session:
    fromStore = TrialDocument(
      package=loadPackage(session, "TRIAL-1"),
      observations=loadObservations(session, "TRIAL-1"),
    )
  path = str(tmp_path / "trial.json")
  exportJson(document, path)
  fromJson = importJson(path)
  assert contentHash(fromStore) == contentHash(document)
  assert contentHash(fromJson) == contentHash(document)


# ---- validated import -----------------------------------------------------

def testImportRejectsMalformedPackage(tmp_path):
  broken = sampleDocument().canonicalDict()
  broken["package"]["treatments"] = broken["package"]["treatments"][:1]  # min is 2
  path = tmp_path / "broken.json"
  path.write_text(__import__("json").dumps(broken))
  with pytest.raises(ValidationError):
    importJson(str(path))


def testImportRejectsUnknownTopLevelKey(tmp_path):
  data = sampleDocument().canonicalDict()
  data["unexpected"] = True
  path = tmp_path / "extra.json"
  path.write_text(__import__("json").dumps(data))
  with pytest.raises(ValidationError):
    importJson(str(path))


# ---- CSV export -----------------------------------------------------------

def testObservationsCsvCarriesLayoutAndValues(tmp_path):
  document = sampleDocument()
  layout = generateRcbdLayout(document.package)
  plotInfo = {plot.plotNumber: (plot.block, plot.treatmentCode) for plot in layout.plots}
  path = tmp_path / "obs.csv"
  exportObservationsCsv(document, str(path))

  with path.open() as handle:
    rows = list(csv.DictReader(handle))
  assert list(rows[0].keys()) == ["plotNumber", "block", "treatment", "assessmentCode", "value"]
  assert len(rows) == len(document.observations)
  for row in rows:
    expectedBlock, expectedTreatment = plotInfo[int(row["plotNumber"])]
    assert int(row["block"]) == expectedBlock
    assert row["treatment"] == expectedTreatment


def testObservationsCsvMissingValueIsEmpty(tmp_path):
  document = sampleDocument()
  missingPlot = document.observations[0].plotNumber  # this YIELD was set to None
  path = tmp_path / "obs.csv"
  exportObservationsCsv(document, str(path))
  with path.open() as handle:
    rows = list(csv.DictReader(handle))
  missingRow = next(r for r in rows if int(r["plotNumber"]) == missingPlot and r["assessmentCode"] == "YIELD")
  assert missingRow["value"] == ""


def testObservationsCsvRejectsUnknownPlot(tmp_path):
  package = samplePackage()
  document = TrialDocument(
    package=package,
    observations=[Observation(plotNumber=999999, assessmentCode="YIELD", value=1.0)],
  )
  with pytest.raises(ExchangeError, match="not in the layout"):
    exportObservationsCsv(document, str(tmp_path / "obs.csv"))
