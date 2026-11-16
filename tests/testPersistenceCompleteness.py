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

from pydantic import BaseModel

from openfurrow import TrialDocument, TrialPackage, Workspace, contentHash, schemaVersion
from openfurrow.design import generateRcbdLayout

# Every optional field populated with a value that differs from its default, and both a
# numeric assessment (which carries transform/measurementKind/range) and an ordinal one
# (which carries allowedValues) so both branches are covered.
_maximalPackage = {
  "schemaVersion": schemaVersion,
  "trial": {
    "trialCode": "MAX-1", "title": "Maximal trial", "crop": "Barley", "season": "2025",
    "site": "North Field", "objective": "Compare programs",
    "investigator": "Dr. Q", "organization": "Institute Z",
  },
  "treatments": [
    {"treatmentCode": "UTC", "name": "Untreated control", "role": "untreatedControl"},
    {"treatmentCode": "T2", "name": "Program", "role": "test", "lines": [
      {"product": "Fungicide X", "kind": "fungicide", "formulationType": "SC",
       "activeSubstances": [
         {"name": "difenoconazole", "concentration": {"value": 125, "unit": "g/L"}},
         {"name": "azoxystrobin", "concentration": {"value": 200, "unit": "g/L"}},
       ],
       "rate": {"value": 0.125, "unit": "kg/ha"}, "rateBasis": "activeSubstance",
       "applicationCodes": ["B", "A"]},
      {"product": "Adjuvant A", "kind": "adjuvant", "formulationType": "EC",
       "activeSubstances": [{"name": "methylated seed oil", "concentration": {"value": 70, "unit": "% w/w"}}],
       "rate": {"value": 0.5, "unit": "L/ha"}, "rateBasis": "formulatedProduct",
       "applicationCodes": ["B"]},
    ]},
  ],
  # Lines, substances and applications are listed out of alphabetical order on purpose:
  # an exact round trip then also proves their order is kept.
  "applications": [
    {"applicationCode": "B", "timing": "BBCH 39", "date": "2025-05-20", "time": "09:30",
     "method": "Broadcast spray", "placement": "Foliar", "equipment": "Plot sprayer", "nozzle": "XR 11002",
     "pressure": {"value": 250, "unit": "kPa"}, "sprayQuality": "medium",
     "travelSpeed": {"value": 6, "unit": "km/h"}, "sprayVolume": {"value": 200, "unit": "L/ha"},
     "cropStage": "BBCH 37", "targetStage": "First pustules",
     "airTemperature": {"value": 14.5, "unit": "C"}, "relativeHumidity": 64.5,
     "windSpeed": {"value": 2.1, "unit": "m/s"}, "cloudCover": 30, "soilMoisture": "moist",
     "notes": "Dew on the crop"},
    {"applicationCode": "A", "timing": "BBCH 31"},
  ],
  "design": {"designType": "rcbd", "replications": 3, "randomizationMethod": "sha256FisherYates1", "randomizationSeed": 99},
  "ratings": [
    {"ratingCode": "CT", "name": "Insect count", "ratingType": "pest count", "partRated": "whole plant",
     "method": "Beat sheet, 10 plants", "dataType": "numeric", "unit": "per m2", "minValue": 0,
     "maxValue": 500, "transform": "sqrt", "measurementKind": "count"},
    {"ratingCode": "SEV", "name": "Severity", "dataType": "ordinal", "allowedValues": ["none", "low", "moderate", "high"]}
  ],
  "assessments": [
    {"assessmentCode": "CT14", "ratingCode": "CT", "timing": "14 DA-B", "date": "2025-06-03",
     "cropStage": "BBCH 59", "targetStage": "Adults", "timedFromApplicationCode": "B",
     "assessedBy": "Field team", "sampleSize": {"value": 10, "unit": "plants"}, "notes": "Windy"},
    {"assessmentCode": "SEV", "ratingCode": "SEV"},
    {"assessmentCode": "CT0", "ratingCode": "CT", "timing": "Before B"}
  ],
}


def _package():
  return TrialPackage.model_validate(_maximalPackage)


# ---- the maximal package really is maximal ---------------------------------

# The one field that cannot differ from its default: there is a single design.
_cannotDiffer = {("DesignSpecification", "designType")}


def _recordPopulated(model: BaseModel, populated: dict[tuple[str, str], bool]) -> None:
  for name, field in type(model).model_fields.items():
    value = getattr(model, name)
    key = (type(model).__name__, name)
    isSet = value is not None and value != [] and value != field.default
    populated[key] = populated.get(key, False) or isSet
    for child in value if isinstance(value, list) else [value]:
      if isinstance(child, BaseModel):
        _recordPopulated(child, populated)


def testMaximalPackagePopulatesEveryField():
  """A field added to the schema and left out of the package above fails here.

  Without this the round trips below would pass for the new field with a default on both
  sides, which is how a dropped column goes unnoticed.
  """
  populated: dict[tuple[str, str], bool] = {}
  _recordPopulated(_package(), populated)
  assert sorted(key for key, isSet in populated.items() if not isSet) == sorted(_cannotDiffer)


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


def testExportWritesQuantitiesAndDatesLocaleNeutral(tmp_path):
  """A date and a time leave as ISO 8601 and a quantity as a dot-decimal value beside its unit."""
  workspace = Workspace.create(str(tmp_path / "a.db"))
  workspace.addPackage(_package())
  jsonPath = tmp_path / "doc.json"
  workspace.exportDocument("MAX-1", str(jsonPath))
  exported = json.loads(jsonPath.read_text(encoding="utf-8"))["package"]
  assert exported["applications"][0]["date"] == "2025-05-20"
  assert exported["applications"][0]["time"] == "09:30:00"
  assert exported["applications"][0]["airTemperature"] == {"value": 14.5, "unit": "C"}
  assert exported["treatments"][1]["lines"][0]["rate"] == {"value": 0.125, "unit": "kg/ha"}
  assert exported["treatments"][1]["lines"][0]["applicationCodes"] == ["B", "A"]


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
    data["ratings"][0]["transform"] = "none"
  assert _hashWith(lambda data: None) != _hashWith(toNone)


def testMeasurementKindEntersContentHash():
  def toUnspecified(data):
    data["ratings"][0]["measurementKind"] = "unspecified"
  assert _hashWith(lambda data: None) != _hashWith(toUnspecified)


def testAssessmentDateEntersContentHash():
  def changeDate(data):
    data["assessments"][0]["date"] = "2025-06-04"
  assert _hashWith(lambda data: None) != _hashWith(changeDate)


def testRatingAnAssessmentTakesEntersContentHash():
  def otherRating(data):
    data["assessments"][2]["ratingCode"] = "SEV"
  assert _hashWith(lambda data: None) != _hashWith(otherRating)


def testTreatmentRateEntersContentHash():
  def changeRate(data):
    data["treatments"][1]["lines"][0]["rate"]["value"] = 0.25
  assert _hashWith(lambda data: None) != _hashWith(changeRate)


def testRateBasisEntersContentHash():
  """The same number on the other basis is another dose, so it is another trial."""
  def changeBasis(data):
    data["treatments"][1]["lines"][0]["rateBasis"] = "formulatedProduct"
  assert _hashWith(lambda data: None) != _hashWith(changeBasis)


def testTreatmentRoleEntersContentHash():
  def dropRole(data):
    del data["treatments"][1]["role"]
  assert _hashWith(lambda data: None) != _hashWith(dropRole)


def testApplicationsALineNamesEnterContentHash():
  def dropSecondApplication(data):
    data["treatments"][1]["lines"][0]["applicationCodes"] = ["B"]
  assert _hashWith(lambda data: None) != _hashWith(dropSecondApplication)


def testApplicationDateEntersContentHash():
  def changeDate(data):
    data["applications"][0]["date"] = "2025-05-21"
  assert _hashWith(lambda data: None) != _hashWith(changeDate)


def testNumericBoundsEnterContentHash():
  def changeBound(data):
    data["ratings"][0]["maxValue"] = 400
  assert _hashWith(lambda data: None) != _hashWith(changeBound)
