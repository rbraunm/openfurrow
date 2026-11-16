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
from openfurrow.design import generateLayout
from storeHelpers import standardStudy, standardStudyAt

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
  "siteDetails": {
    "address": "North Field, Station Road", "latitude": 52.1234, "longitude": -0.5678,
    "elevation": {"value": 85, "unit": "m"}, "setting": "field", "exposure": "Open, south-facing", "slope": "2 %",
  },
  "planting": {
    "cultivar": "Laureate", "cropEPPOCode": "HORVX", "sowingDate": "2025-03-20",
    "seedingRate": {"value": 350, "unit": "seeds/m2"}, "plantDensity": {"value": 290, "unit": "plants/m2"},
    "rowSpacing": {"value": 12.5, "unit": "cm"}, "inRowSpacing": {"value": 2.5, "unit": "cm"},
    "sowingDepth": {"value": 3, "unit": "cm"}, "emergenceDate": "2025-04-02",
    "precedingCrop": "Oilseed rape", "tillage": "Plough, then power harrow", "trainingSystem": "None, arable",
    "rootstock": "Own roots", "plantedYear": 2025, "notes": "Rolled after drilling",
  },
  "soil": {
    "soilType": "Luvisol", "texture": "silty clay loam", "pH": 6.8, "pHMethod": "water 1:2.5",
    "organicMatter": 2.4, "seedbedQuality": "fine", "fertilizerRegime": "120 kg N/ha in two splits",
    "notes": "Sampled 0-20 cm",
  },
  # Two days, so an exact round trip also proves their order is kept.
  "weather": [
    {"date": "2025-05-19", "rainfall": {"value": 0, "unit": "mm"}, "irrigation": {"value": 15, "unit": "mm"},
     "minimumTemperature": {"value": -0.5, "unit": "C"}, "maximumTemperature": {"value": 18.5, "unit": "C"},
     "notes": "Ground frost"},
    {"date": "2025-05-20", "rainfall": {"value": 4.2, "unit": "mm"}},
  ],
  "targets": [
    {"targetCode": "APHID", "name": "Bird cherry-oat aphid", "kind": "insect",
     "scientificName": "Rhopalosiphum padi", "eppoCode": "RHOPPA"},
  ],
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
  "design": {"designType": "rcbd", "replications": 3, "randomizationMethod": "sha256FisherYates1", "randomizationSeed": 99,
             "firstBlockInTreatmentOrder": True, "checkArrangement": "paired",
             "plotDimensions": {"grossLength": {"value": 10, "unit": "m"}, "grossWidth": {"value": 2, "unit": "m"},
                                "netLength": {"value": 8, "unit": "m"}, "netWidth": {"value": 1.5, "unit": "m"},
                                "alleyWidth": {"value": 0.5, "unit": "m"}, "notes": "Discard rows at both sides"}},
  "ratings": [
    {"ratingCode": "CT", "name": "Insect count", "ratingType": "pest count", "partRated": "whole plant",
     "method": "Beat sheet, 10 plants", "targetCode": "APHID", "dataType": "numeric", "unit": "per m2", "minValue": 0,
     "maxValue": 500, "transform": "sqrt", "transformOffset": 0.5, "measurementKind": "count"},
    {"ratingCode": "SEV", "name": "Severity", "dataType": "ordinal", "allowedValues": ["none", "low", "moderate", "high"]}
  ],
  "assessments": [
    {"assessmentCode": "CT14", "ratingCode": "CT", "timing": "14 DA-B", "date": "2025-06-03",
     "cropStage": "BBCH 59", "targetStage": "Adults", "timedFromApplicationCode": "B",
     "assessedBy": "Field team", "sampleSize": {"value": 10, "unit": "plants"}, "notes": "Windy",
     "efficacy": {"method": "hendersonTilton", "baselineAssessmentCode": "CT0"}},
    {"assessmentCode": "SEV", "ratingCode": "SEV"},
    {"assessmentCode": "CT0", "ratingCode": "CT", "timing": "Before B", "untreatedCheck": "excluded",
     "subsamples": {"count": 4, "rule": "sum"}}
  ],
}


# The fields only a split plot uses. Levels and treatments are listed out of order on
# purpose, so an exact round trip also proves their order is kept.
_splitPlotPackage = {
  "schemaVersion": schemaVersion,
  "trial": {"trialCode": "SPLIT-1", "title": "Split plot", "crop": "Rice", "season": "1984",
            "site": "Field 3", "objective": "Nitrogen by variety"},
  "factors": [
    {"factorCode": "N", "name": "Nitrogen", "levels": [
      {"levelCode": "N90", "name": "90 kg N/ha"}, {"levelCode": "N0", "name": "0 kg N/ha"}]},
    {"factorCode": "V", "name": "Variety", "levels": [
      {"levelCode": "IR8", "name": "IR8"}, {"levelCode": "PETA", "name": "Peta"}]},
  ],
  "treatments": [
    {"treatmentCode": "N0-IR8", "name": "0 N, IR8", "factorLevels": {"N": "N0", "V": "IR8"}},
    {"treatmentCode": "N0-PETA", "name": "0 N, Peta", "factorLevels": {"N": "N0", "V": "PETA"}},
    {"treatmentCode": "N90-PETA", "name": "90 N, Peta", "factorLevels": {"N": "N90", "V": "PETA"}},
    {"treatmentCode": "N90-IR8", "name": "90 N, IR8", "factorLevels": {"N": "N90", "V": "IR8"}},
  ],
  "design": {"designType": "splitPlot", "replications": 3, "mainPlotFactor": "N", "subPlotFactor": "V",
             "randomizationMethod": "sha256FisherYates1", "randomizationSeed": 5},
  "ratings": [{"ratingCode": "Y", "name": "Grain yield", "dataType": "numeric", "unit": "kg/ha"}],
  "assessments": [{"assessmentCode": "Y", "ratingCode": "Y"}],
}


def _package():
  return TrialPackage.model_validate(_maximalPackage)


def _splitPlot():
  return TrialPackage.model_validate(_splitPlotPackage)


# ---- the maximal package really is maximal ---------------------------------

# Every field is set to something other than its default in one of the two packages.
_cannotDiffer: set[tuple[str, str]] = set()


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
  """A field added to the schema and left out of both packages above fails here.

  Without this the round trips below would pass for the new field with a default on both
  sides, which is how a dropped column goes unnoticed.
  """
  populated: dict[tuple[str, str], bool] = {}
  _recordPopulated(_package(), populated)
  _recordPopulated(_splitPlot(), populated)
  assert sorted(key for key, isSet in populated.items() if not isSet) == sorted(_cannotDiffer)


# ---- exact round-trips through every persistence path ---------------------

def testStoreRoundTripIsExact(tmp_path, newStore):
  """Every field survives the SQLite store, not just the ones with non-default samples."""
  workspace = Workspace.create(newStore("trials"))
  package = _package()
  workspace.addPackage(package, standardStudy(workspace))
  assert workspace.loadPackage("MAX-1") == package


def testSplitPlotStoreRoundTripIsExact(tmp_path, newStore):
  workspace = Workspace.create(newStore("trials"))
  workspace.addPackage(_splitPlot(), standardStudy(workspace))
  assert workspace.loadPackage("SPLIT-1") == _splitPlot()
  plots = workspace.layoutFor("SPLIT-1").plots
  assert sorted({plot.mainPlot for plot in plots}) == [1, 2]


def testSplitPlotExchangeRoundTripIsExact(tmp_path, newStore):
  source = Workspace.create(newStore("a"))
  source.addPackage(_splitPlot(), standardStudy(source))
  jsonPath = str(tmp_path / "doc.json")
  source.exportDocument("SPLIT-1", jsonPath)
  destination = Workspace.create(newStore("b"))
  destination.importDocument(jsonPath, standardStudy(destination))
  assert destination.loadPackage("SPLIT-1") == _splitPlot()
  assert destination.contentHashFor("SPLIT-1") == source.contentHashFor("SPLIT-1")


def testJsonExchangeRoundTripIsExact(tmp_path, newStore):
  """Every field survives JSON export and re-import into a fresh store."""
  source = Workspace.create(newStore("a"))
  source.addPackage(_package(), standardStudy(source))
  jsonPath = str(tmp_path / "doc.json")
  source.exportDocument("MAX-1", jsonPath)

  destination = Workspace.create(newStore("b"))
  destination.importDocument(jsonPath, standardStudy(destination))
  assert destination.loadPackage("MAX-1") == _package()


def testExportWritesQuantitiesAndDatesLocaleNeutral(tmp_path, newStore):
  """A date and a time leave as ISO 8601 and a quantity as a dot-decimal value beside its unit."""
  workspace = Workspace.create(newStore("a"))
  workspace.addPackage(_package(), standardStudy(workspace))
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
  layout = generateLayout(package)
  return contentHash(
    TrialDocument(package=package, layout=layout.plots, checkPlots=layout.checkPlots, observations=[])
  )


def testRandomizationSeedEntersContentHash():
  def changeSeed(data):
    data["design"]["randomizationSeed"] = 100
  assert _hashWith(lambda data: None) != _hashWith(changeSeed)


# ---- a layout made elsewhere is kept exactly (decision 0015) ---------------

def testImportedLayoutSurvivesStoreAndExchange(tmp_path, newStore):
  """Plot numbers and assignments that no generator produced come back unchanged."""
  data = copy.deepcopy(_maximalPackage)
  data["design"] = {"designType": "rcbd", "replications": 3, "randomizationMethod": "imported"}
  del data["assessments"][0]["efficacy"]
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

  first = Workspace.create(newStore("a"))
  assert first.importDocument(str(sourcePath), standardStudy(first)) == "MAX-1"
  stored = first.layoutFor("MAX-1").plots
  assert [plot.model_dump(exclude_none=True) for plot in stored] == plots
  assert first.loadPackage("MAX-1").design.randomizationSeed is None

  exportedPath = str(tmp_path / "exported.json")
  first.exportDocument("MAX-1", exportedPath)
  second = Workspace.create(newStore("b"))
  second.importDocument(exportedPath, standardStudy(second))
  assert second.contentHashFor("MAX-1") == first.contentHashFor("MAX-1")
  assert [plot.model_dump(exclude_none=True) for plot in second.layoutFor("MAX-1").plots] == plots


def testFirstBlockInTreatmentOrderEntersContentHash():
  def shuffleEveryBlock(data):
    data["design"]["firstBlockInTreatmentOrder"] = False
  assert _hashWith(lambda data: None) != _hashWith(shuffleEveryBlock)


def testTransformEntersContentHash():
  """ADR 0006: the transform enters the content hash, so it cannot silently change results."""
  def toNone(data):
    data["ratings"][0]["transform"] = "none"
    data["ratings"][0]["transformOffset"] = 0.0
  assert _hashWith(lambda data: None) != _hashWith(toNone)


def testTransformOffsetEntersContentHash():
  def changeOffset(data):
    data["ratings"][0]["transformOffset"] = 1.0
  assert _hashWith(lambda data: None) != _hashWith(changeOffset)


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
    data["assessments"][1]["ratingCode"] = "CT"
  assert _hashWith(lambda data: None) != _hashWith(otherRating)


def testTargetARatingNamesEntersContentHash():
  def dropTarget(data):
    del data["ratings"][0]["targetCode"]
  assert _hashWith(lambda data: None) != _hashWith(dropTarget)


def testSoilPHEntersContentHash():
  def changePH(data):
    data["soil"]["pH"] = 6.9
  assert _hashWith(lambda data: None) != _hashWith(changePH)


def testRainfallEntersContentHash():
  def changeRain(data):
    data["weather"][1]["rainfall"]["value"] = 4.3
  assert _hashWith(lambda data: None) != _hashWith(changeRain)


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
