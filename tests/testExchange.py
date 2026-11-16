# SPDX-License-Identifier: Apache-2.0
"""Tests for portable exchange (JSON and CSV).

The central guarantee is that a trial is never trapped in the store: the database
and a JSON export agree on the content hash, so the exported file is a faithful,
movable copy. JSON export is deterministic and its import is validated; the CSV
export carries the layout (block and treatment) and represents missing values as
empty cells.
"""

import csv
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from openfurrow import schemaVersion
from openfurrow.design import generateRcbdLayout
from openfurrow.exchange import ExchangeError, exportJson, exportObservationsCsv, importJson
from openfurrow.schema import TrialDocument, TrialPackage, contentHash
from openfurrow.schema.observation import Observation
from openfurrow.store import (
  createDatabase,
  loadLayout,
  loadObservations,
  loadPackage,
  savePackage,
  saveObservations,
  sessionScope,
)


def samplePackage(trialCode="TRIAL-1"):
  return TrialPackage.model_validate({
    "schemaVersion": schemaVersion,
    "trial": {"trialCode": trialCode, "title": "Sample trial", "crop": "Wheat", "season": "2025",
              "site": "Field A", "objective": "Compare fungicides", "investigator": "Dr. X"},
    "treatments": [
      {"treatmentCode": "T1", "name": "Untreated control", "role": "untreatedControl"},
      {"treatmentCode": "T2", "name": "Fungicide X", "role": "test", "lines": [
        {"product": "Prod X", "rate": {"value": 2.5, "unit": "L/ha"}, "rateBasis": "formulatedProduct",
         "applicationCodes": ["A"]},
      ]},
      {"treatmentCode": "T3", "name": "Fungicide Y", "role": "reference", "lines": [
        {"product": "Prod Y", "rate": {"value": 1.0, "unit": "kg/ha"}, "rateBasis": "formulatedProduct",
         "applicationCodes": ["A"]},
      ]},
    ],
    "applications": [{"applicationCode": "A", "timing": "BBCH 30"}],
    "design": {"designType": "rcbd", "replications": 4, "randomizationMethod": "sha256FisherYates1", "randomizationSeed": 42},
    "ratings": [
      {"ratingCode": "YIELD", "name": "Grain yield", "dataType": "numeric", "unit": "kg/ha", "minValue": 0},
      {"ratingCode": "LODGE", "name": "Lodging", "dataType": "ordinal", "allowedValues": ["none", "slight", "severe"]}
    ],
    "assessments": [
      {"assessmentCode": "YIELD", "ratingCode": "YIELD"},
      {"assessmentCode": "LODGE", "ratingCode": "LODGE"}
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
  return TrialDocument(package=package, layout=layout.plots, observations=observations)


def importedDocumentDict():
  """A trial laid out elsewhere: its own plot numbers, no seed, treatments in hand-made order."""
  data = samplePackage("IMPORTED-1").model_dump(mode="json")
  data["design"] = {"designType": "rcbd", "replications": 2, "randomizationMethod": "imported"}
  layout = [
    {"plotNumber": 11, "block": 1, "positionInBlock": 1, "treatmentCode": "T1"},
    {"plotNumber": 12, "block": 1, "positionInBlock": 2, "treatmentCode": "T2"},
    {"plotNumber": 13, "block": 1, "positionInBlock": 3, "treatmentCode": "T3"},
    {"plotNumber": 21, "block": 2, "positionInBlock": 1, "treatmentCode": "T3"},
    {"plotNumber": 22, "block": 2, "positionInBlock": 2, "treatmentCode": "T1"},
    {"plotNumber": 23, "block": 2, "positionInBlock": 3, "treatmentCode": "T2"},
  ]
  observations = [
    {"plotNumber": plot["plotNumber"], "assessmentCode": "YIELD", "value": 50.0 + plot["plotNumber"]}
    for plot in layout
  ]
  return {"package": data, "layout": layout, "observations": observations}


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


def testJsonExportHasLfLineEndingsOnEveryPlatform(tmp_path):
  path = tmp_path / "trial.json"
  exportJson(sampleDocument(), str(path))
  exported = path.read_bytes()
  assert b"\r" not in exported
  assert exported.endswith(b"}\n")


def testDatabaseAndJsonAgreeOnHash(tmp_path):
  # The ownership guarantee: the store and a JSON export describe the same trial.
  document = sampleDocument()
  engine = createDatabase(str(tmp_path / "trials.db"))
  with sessionScope(engine) as session:
    savePackage(session, document.package, document.layout, document.checkPlots)
    saveObservations(session, "TRIAL-1", document.observations)
  with sessionScope(engine) as session:
    fromStore = TrialDocument(
      package=loadPackage(session, "TRIAL-1"),
      layout=loadLayout(session, "TRIAL-1"),
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
  path.write_text(json.dumps(broken))
  with pytest.raises(ExchangeError, match="not a valid trial document"):
    importJson(str(path))


def testImportRejectsUnknownTopLevelKey(tmp_path):
  data = sampleDocument().canonicalDict()
  data["unexpected"] = True
  path = tmp_path / "extra.json"
  path.write_text(json.dumps(data))
  with pytest.raises(ExchangeError, match="not a valid trial document"):
    importJson(str(path))


def testImportRejectsFileThatIsNotJson(tmp_path):
  path = tmp_path / "notJson.json"
  path.write_text("plotNumber,assessmentCode,value\n101,YIELD,1\n")
  with pytest.raises(ExchangeError, match="not valid JSON"):
    importJson(str(path))


# ---- the layout is part of the document (decision 0015) -------------------

def testHashCoversTheLayout():
  data = importedDocumentDict()
  original = contentHash(TrialDocument.model_validate(data))
  # Swap two treatments inside block 2: same package, same observations, another field.
  data["layout"][3]["treatmentCode"], data["layout"][4]["treatmentCode"] = "T1", "T3"
  assert contentHash(TrialDocument.model_validate(data)) != original


def testImportedLayoutSurvivesTheJsonRoundTrip(tmp_path):
  document = TrialDocument.model_validate(importedDocumentDict())
  path = str(tmp_path / "imported.json")
  exportJson(document, path)
  imported = importJson(path)
  assert [plot.plotNumber for plot in imported.layout] == [11, 12, 13, 21, 22, 23]
  assert [plot.treatmentCode for plot in imported.layout] == ["T1", "T2", "T3", "T3", "T1", "T2"]
  assert imported.package.design.randomizationSeed is None
  assert contentHash(imported) == contentHash(document)


def testGeneratedLayoutMustBeWhatItsSeedProduces():
  data = sampleDocument().canonicalDict()
  first, second = data["layout"][0], data["layout"][1]
  first["treatmentCode"], second["treatmentCode"] = second["treatmentCode"], first["treatmentCode"]
  with pytest.raises(ValidationError, match="is not the one method 'sha256FisherYates1' produces from seed 42"):
    TrialDocument.model_validate(data)


def testLayoutMustBeCompleteBlocks():
  data = importedDocumentDict()
  data["layout"][5]["treatmentCode"] = "T1"  # block 2 now holds T1 twice and no T2
  with pytest.raises(ValidationError, match="block 2 is not a complete set"):
    TrialDocument.model_validate(data)


def testLayoutRejectsRepeatedPlotNumber():
  data = importedDocumentDict()
  data["layout"][5]["plotNumber"] = 11
  data["observations"] = []
  with pytest.raises(ValidationError, match=r"plot numbers used more than once: \[11\]"):
    TrialDocument.model_validate(data)


def testObservationOnUnknownPlotRejected():
  data = importedDocumentDict()
  data["observations"].append({"plotNumber": 999999, "assessmentCode": "YIELD", "value": 1.0})
  with pytest.raises(ValidationError, match=r"plots that are not in the layout: \[999999\]"):
    TrialDocument.model_validate(data)


# ---- CSV export -----------------------------------------------------------

def testObservationsCsvCarriesLayoutAndValues(tmp_path):
  document = sampleDocument()
  layout = generateRcbdLayout(document.package)
  plotInfo = {plot.plotNumber: (plot.block, plot.treatmentCode) for plot in layout.plots}
  path = tmp_path / "obs.csv"
  exportObservationsCsv(document, str(path))

  with path.open() as handle:
    rows = list(csv.DictReader(handle))
  assert list(rows[0].keys()) == ["plotNumber", "block", "treatment", "checkFor", "assessmentCode", "subsample", "value"]
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


def testObservationsCsvUsesAnImportedLayout(tmp_path):
  document = TrialDocument.model_validate(importedDocumentDict())
  path = tmp_path / "obs.csv"
  exportObservationsCsv(document, str(path))
  with path.open() as handle:
    rows = list(csv.DictReader(handle))
  assert [(row["plotNumber"], row["block"], row["treatment"]) for row in rows] == [
    ("11", "1", "T1"), ("12", "1", "T2"), ("13", "1", "T3"),
    ("21", "2", "T3"), ("22", "2", "T1"), ("23", "2", "T2"),
  ]
