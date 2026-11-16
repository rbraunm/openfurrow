# SPDX-License-Identifier: Apache-2.0
"""Persistence completeness: no schema field may be silently dropped or unhashed.

This is a guard against a whole bug class, motivated by a real one: the store's
assessment row had no columns for `transform` and `measurementKind`, so a declared
transform was silently lost on save and the analysis then ran on the untransformed
scale after the trial was persisted. The existing round-trip test missed it because its
sample left those fields at their defaults, so equality held on both sides.

The fix here is a *maximal* package -- every optional field set to a non-default value --
driven through each persistence path. If any field is dropped by the SQLite store, by
the JSON exchange, or omitted from the content hash, one of these fails immediately.
When a field is added to the schema, this test must be extended to populate it; a field
that is not exercised here is a field that can be silently lost.
"""

import copy
import json

from openfurrow import TrialDocument, TrialPackage, Workspace, contentHash
from openfurrow.design import generateRcbdLayout

# Every optional field populated with a value that differs from its default, and both a
# numeric assessment (which carries transform/measurementKind/range) and an ordinal one
# (which carries allowedValues) so both branches are covered.
_maximalPackage = {
  "schemaVersion": "0.2.0",
  "trial": {
    "trialCode": "MAX-1", "title": "Maximal trial", "crop": "Barley", "season": "2025",
    "site": "North Field", "objective": "Compare programs",
    "investigator": "Dr. Q", "organization": "Institute Z",
  },
  "treatments": [
    {"treatmentCode": "UTC", "name": "Untreated control"},
    {"treatmentCode": "T2", "name": "Program", "product": "Fungicide X",
     "rate": 2.5, "rateUnit": "L/ha", "timing": "BBCH 30"},
  ],
  "design": {"designType": "rcbd", "replications": 3, "randomizationMethod": "sha256FisherYates1", "randomizationSeed": 99},
  "assessments": [
    {"assessmentCode": "CT", "name": "Insect count", "dataType": "numeric", "unit": "per m2",
     "timing": "14 DAA", "minValue": 0, "maxValue": 500, "transform": "sqrt",
     "measurementKind": "count"},
    {"assessmentCode": "SEV", "name": "Severity", "dataType": "ordinal",
     "allowedValues": ["none", "low", "moderate", "high"]},
  ],
}


def _package():
  return TrialPackage.model_validate(_maximalPackage)


# ---- exact round-trips through every persistence path ---------------------

def testStoreRoundTripIsExact(tmp_path):
  """Every field survives the SQLite store, not just the ones with non-default samples."""
  workspace = Workspace.create(str(tmp_path / "trials.db"))
  package = _package()
  workspace.addPackage(package)
  assert workspace.loadPackage("MAX-1") == package


def testJsonExchangeRoundTripIsExact(tmp_path):
  """Every field survives JSON export and re-import into a fresh store."""
  source = Workspace.create(str(tmp_path / "a.db"))
  source.addPackage(_package())
  jsonPath = str(tmp_path / "doc.json")
  source.exportDocument("MAX-1", jsonPath)

  destination = Workspace.create(str(tmp_path / "b.db"))
  destination.importDocument(jsonPath)
  assert destination.loadPackage("MAX-1") == _package()


# ---- fields that change meaning must change the content hash --------------

def _hashWith(mutate) -> str:
  data = copy.deepcopy(_maximalPackage)
  mutate(data)
  package = TrialPackage.model_validate(data)
  return contentHash(
    TrialDocument(package=package, layout=generateRcbdLayout(package).plots, observations=[])
  )


def testRandomizationSeedEntersContentHash():
  def changeSeed(data):
    data["design"]["randomizationSeed"] = 100
  assert _hashWith(lambda data: None) != _hashWith(changeSeed)


# ---- a layout made elsewhere is kept exactly (decision 0015) ---------------

def testImportedLayoutSurvivesStoreAndExchange(tmp_path):
  """Plot numbers and assignments that no generator produced come back unchanged."""
  data = copy.deepcopy(_maximalPackage)
  data["design"] = {"designType": "rcbd", "replications": 3, "randomizationMethod": "imported"}
  plots = [
    {"plotNumber": 7, "block": 1, "positionInBlock": 1, "treatmentCode": "UTC"},
    {"plotNumber": 8, "block": 1, "positionInBlock": 2, "treatmentCode": "T2"},
    {"plotNumber": 31, "block": 2, "positionInBlock": 1, "treatmentCode": "T2"},
    {"plotNumber": 32, "block": 2, "positionInBlock": 2, "treatmentCode": "UTC"},
    {"plotNumber": 55, "block": 3, "positionInBlock": 1, "treatmentCode": "UTC"},
    {"plotNumber": 56, "block": 3, "positionInBlock": 2, "treatmentCode": "T2"},
  ]
  sourcePath = tmp_path / "imported.json"
  sourcePath.write_text(json.dumps({"package": data, "layout": plots, "observations": []}), encoding="utf-8")

  first = Workspace.create(str(tmp_path / "a.db"))
  assert first.importDocument(str(sourcePath)) == "MAX-1"
  stored = first.layoutFor("MAX-1").plots
  assert [plot.model_dump() for plot in stored] == plots
  assert first.loadPackage("MAX-1").design.randomizationSeed is None

  exportedPath = str(tmp_path / "exported.json")
  first.exportDocument("MAX-1", exportedPath)
  second = Workspace.create(str(tmp_path / "b.db"))
  second.importDocument(exportedPath)
  assert second.contentHashFor("MAX-1") == first.contentHashFor("MAX-1")
  assert [plot.model_dump() for plot in second.layoutFor("MAX-1").plots] == plots


def testTransformEntersContentHash():
  """ADR 0006: the transform enters the content hash, so it cannot silently change results."""
  def toNone(data):
    data["assessments"][0]["transform"] = "none"
  assert _hashWith(lambda data: None) != _hashWith(toNone)


def testMeasurementKindEntersContentHash():
  def toUnspecified(data):
    data["assessments"][0]["measurementKind"] = "unspecified"
  assert _hashWith(lambda data: None) != _hashWith(toUnspecified)


def testTreatmentRateEntersContentHash():
  def changeRate(data):
    data["treatments"][1]["rate"] = 3.0
  assert _hashWith(lambda data: None) != _hashWith(changeRate)


def testNumericBoundsEnterContentHash():
  def changeBound(data):
    data["assessments"][0]["maxValue"] = 400
  assert _hashWith(lambda data: None) != _hashWith(changeBound)
