# SPDX-License-Identifier: Apache-2.0
"""Tests for the trial package schema.

Each test exercises the real models. The valid-construction tests assert
concrete field values and the derived plot count; the rejection tests assert
that a specific malformed package raises and, where the rule is enforced by a
custom validator, that the failure names the offending entity.
"""

import datetime

import pytest
from pydantic import ValidationError

from openfurrow.schema import (
  AssessmentDataType,
  DesignType,
  ProductKind,
  Quantity,
  RateBasis,
  SoilMoisture,
  TargetKind,
  TreatmentRole,
  TrialPackage,
)


def buildPackage(packageDict):
  return TrialPackage.model_validate(packageDict)


def errorMessages(excInfo):
  return [error["msg"] for error in excInfo.value.errors()]


# ---- valid construction -------------------------------------------------

def testValidPackageConstructs(validPackageDict):
  package = buildPackage(validPackageDict)
  assert package.trial.trialCode == "ESV-2025-01"
  assert len(package.treatments) == 3
  assert package.design.designType is DesignType.rcbd
  assert package.design.randomizationSeed == 42
  assert package.ratings[1].dataType is AssessmentDataType.ordinal


def testPlotCountIsTreatmentsTimesReplications(validPackageDict):
  # 3 treatments x 4 replications.
  assert buildPackage(validPackageDict).plotCount == 12


def testPlotCountTracksDesignChange(validPackageDict):
  validPackageDict["design"]["replications"] = 6
  # Still 3 treatments, now 6 replications -> 18; proves the value is derived.
  assert buildPackage(validPackageDict).plotCount == 18


def testTreatmentCarriesItsRoleAndLines(validPackageDict):
  package = buildPackage(validPackageDict)
  control, program, reference = package.treatments
  assert control.role is TreatmentRole.untreatedControl
  assert control.lines == []
  assert program.role is TreatmentRole.test
  assert reference.role is TreatmentRole.reference
  line = program.lines[0]
  assert line.product == "Fungicide A"
  assert line.rate == Quantity(value=2.5, unit="L/ha")
  assert line.rateBasis is RateBasis.formulatedProduct
  assert line.applicationCodes == ["GS31"]
  assert [application.timing for application in package.applications] == ["BBCH 31", "BBCH 39"]


def testTreatmentRoleIsNotAssumed(validPackageDict):
  # A treatment that states no role has none: nothing reads one out of its name.
  del validPackageDict["treatments"][0]["role"]
  assert buildPackage(validPackageDict).treatments[0].role is None


def testMixtureAndProgramAreLinesOfOneTreatment(validPackageDict):
  # Two products at one application are a mixture; one product at two is a program.
  validPackageDict["treatments"][1]["lines"] = [
    {"product": "Fungicide A", "kind": "fungicide", "formulationType": "SC",
     "activeSubstances": [{"name": "azoxystrobin", "concentration": {"value": 250, "unit": "g/L"}}],
     "rate": {"value": 1.0, "unit": "L/ha"}, "rateBasis": "formulatedProduct",
     "applicationCodes": ["GS31", "GS39"]},
    {"product": "Wetter W", "kind": "adjuvant", "rate": {"value": 0.1, "unit": "% v/v"},
     "rateBasis": "formulatedProduct", "applicationCodes": ["GS31"]},
  ]
  first, second = buildPackage(validPackageDict).treatments[1].lines
  assert first.kind is ProductKind.fungicide
  assert first.formulationType == "SC"
  assert first.activeSubstances[0].concentration == Quantity(value=250.0, unit="g/L")
  assert first.applicationCodes == ["GS31", "GS39"]
  assert second.kind is ProductKind.adjuvant
  assert second.activeSubstances == []


def testNumericRangeWithMinBelowMaxAccepted(validPackageDict):
  validPackageDict["ratings"][0]["minValue"] = 0.0
  validPackageDict["ratings"][0]["maxValue"] = 20000.0
  package = buildPackage(validPackageDict)
  assert package.ratings[0].maxValue == 20000.0


# ---- schema version ------------------------------------------------------

def testUnsupportedSchemaVersionRejected(validPackageDict):
  validPackageDict["schemaVersion"] = "99.0"
  with pytest.raises(ValidationError) as excInfo:
    buildPackage(validPackageDict)
  assert any("schemaVersion '99.0' is not supported" in message
             for message in errorMessages(excInfo))


# ---- treatment rules ----------------------------------------------------

def firstLine(packageDict):
  return packageDict["treatments"][1]["lines"][0]


def rejection(packageDict):
  with pytest.raises(ValidationError) as excInfo:
    buildPackage(packageDict)
  return excInfo


def testRateWithoutUnitRejected(validPackageDict):
  del firstLine(validPackageDict)["rate"]["unit"]
  errors = rejection(validPackageDict).value.errors()
  assert [(error["type"], error["loc"][-2:]) for error in errors] == [("missing", ("rate", "unit"))]


def testLineWithoutRateRejected(validPackageDict):
  del firstLine(validPackageDict)["rate"]
  errors = rejection(validPackageDict).value.errors()
  assert [(error["type"], error["loc"][-1]) for error in errors] == [("missing", "rate")]


def testNonPositiveRateRejected(validPackageDict):
  firstLine(validPackageDict)["rate"]["value"] = 0.0
  assert any("a rate must be greater than zero, got 0.0" in message
             for message in errorMessages(rejection(validPackageDict)))


@pytest.mark.parametrize("notANumber", [float("nan"), float("inf")])
def testRateThatIsNotAFiniteNumberRejected(validPackageDict, notANumber):
  # A rate of NaN is not below zero, so only an explicit rule keeps it out.
  firstLine(validPackageDict)["rate"]["value"] = notANumber
  errors = rejection(validPackageDict).value.errors()
  assert [(error["type"], error["loc"][-2:]) for error in errors] == [("finite_number", ("rate", "value"))]


def testRateBasisMustBeStated(validPackageDict):
  # Product or active substance: a dose read on the wrong basis is a wrong dose.
  del firstLine(validPackageDict)["rateBasis"]
  errors = rejection(validPackageDict).value.errors()
  assert [(error["type"], error["loc"][-1]) for error in errors] == [("missing", "rateBasis")]


def testUntreatedControlWithProductLinesRejected(validPackageDict):
  validPackageDict["treatments"][0]["lines"] = [dict(firstLine(validPackageDict))]
  assert any("treatment 'T1': an untreated control has no product lines" in message
             for message in errorMessages(rejection(validPackageDict)))


def testOtherControlMayHaveProductLines(validPackageDict):
  # A control that is itself treated, e.g. a standard seed dressing on every plot.
  validPackageDict["treatments"][0]["role"] = "otherControl"
  validPackageDict["treatments"][0]["lines"] = [dict(firstLine(validPackageDict))]
  control = buildPackage(validPackageDict).treatments[0]
  assert control.role is TreatmentRole.otherControl
  assert [line.product for line in control.lines] == ["Fungicide A"]


def testActiveSubstanceListedTwiceRejected(validPackageDict):
  firstLine(validPackageDict)["activeSubstances"] = [{"name": "azoxystrobin"}, {"name": "azoxystrobin"}]
  assert any("product 'Fungicide A': an active substance is listed more than once" in message
             for message in errorMessages(rejection(validPackageDict)))


def testNonPositiveConcentrationRejected(validPackageDict):
  firstLine(validPackageDict)["activeSubstances"] = [
    {"name": "azoxystrobin", "concentration": {"value": 0, "unit": "g/L"}},
  ]
  assert any("an active substance's concentration must be greater than zero, got 0.0" in message
             for message in errorMessages(rejection(validPackageDict)))


# ---- application rules --------------------------------------------------

def testLineNamingUndeclaredApplicationRejected(validPackageDict):
  firstLine(validPackageDict)["applicationCodes"] = ["GS31", "GS99"]
  assert any(
    "treatment 'T2', product 'Fungicide A': application(s) ['GS99'] are not declared in the package"
    in message for message in errorMessages(rejection(validPackageDict))
  )


def testLineWithoutAnApplicationRejected(validPackageDict):
  firstLine(validPackageDict)["applicationCodes"] = []
  errors = rejection(validPackageDict).value.errors()
  assert [(error["type"], error["loc"][-1]) for error in errors] == [("too_short", "applicationCodes")]


def testLineNamingAnApplicationTwiceRejected(validPackageDict):
  firstLine(validPackageDict)["applicationCodes"] = ["GS31", "GS31"]
  assert any("product 'Fungicide A': an application is named more than once" in message
             for message in errorMessages(rejection(validPackageDict)))


def testDuplicateApplicationCodeRejected(validPackageDict):
  validPackageDict["applications"][1]["applicationCode"] = "GS31"
  assert any("duplicate applicationCode values: ['GS31']" in message
             for message in errorMessages(rejection(validPackageDict)))


def testApplicationNoLineNamesIsKept(validPackageDict):
  # A pass over the whole trial (a maintenance spray) belongs to the record too.
  validPackageDict["applications"].append({"applicationCode": "M1", "notes": "Whole-trial insecticide"})
  codes = [application.applicationCode for application in buildPackage(validPackageDict).applications]
  assert codes == ["GS31", "GS39", "M1"]


def testApplicationRecordsWhatWasDone(validPackageDict):
  validPackageDict["applications"][0].update({
    "date": "2025-05-02", "time": "09:30", "method": "Broadcast spray", "placement": "Foliar",
    "equipment": "Plot sprayer", "nozzle": "XR 11002", "pressure": {"value": 250, "unit": "kPa"},
    "sprayQuality": "medium", "travelSpeed": {"value": 6, "unit": "km/h"},
    "sprayVolume": {"value": 200, "unit": "L/ha"}, "cropStage": "BBCH 31", "targetStage": "First pustules",
    "airTemperature": {"value": -1.5, "unit": "C"}, "relativeHumidity": 64, "windSpeed": {"value": 0, "unit": "m/s"},
    "cloudCover": 100, "soilMoisture": "moist", "notes": "Dew on the crop",
  })
  application = buildPackage(validPackageDict).applications[0]
  assert application.date == datetime.date(2025, 5, 2)
  assert application.time == datetime.time(9, 30)
  assert (application.sprayQuality, application.travelSpeed) == ("medium", Quantity(value=6.0, unit="km/h"))
  assert application.pressure == Quantity(value=250.0, unit="kPa")
  # A temperature may be below zero and the air may be still; a pressure may be neither.
  assert application.airTemperature == Quantity(value=-1.5, unit="C")
  assert application.windSpeed == Quantity(value=0.0, unit="m/s")
  assert application.soilMoisture is SoilMoisture.moist
  assert (application.relativeHumidity, application.cloudCover) == (64.0, 100.0)


@pytest.mark.parametrize("written", ["02/05/2025", "2025-5-2", "20250502", "2025-05-02T00:00:00", 0, 1746144000])
def testApplicationDateNotWrittenAsADateRejected(validPackageDict, written):
  # A number would otherwise be read as seconds since 1970 and become a date without a word.
  validPackageDict["applications"][0]["date"] = written
  assert any(f"a date is written YYYY-MM-DD, got {written!r}" in message
             for message in errorMessages(rejection(validPackageDict)))


@pytest.mark.parametrize("written, read", [("09:30", datetime.time(9, 30)), ("23:59:59", datetime.time(23, 59, 59))])
def testApplicationTimeIsTheClockAtTheSite(validPackageDict, written, read):
  validPackageDict["applications"][0]["time"] = written
  assert buildPackage(validPackageDict).applications[0].time == read


@pytest.mark.parametrize("written", ["9:30", "0930", "09:30Z", "09:30:00+02:00", "09:30:00.5", "9.30 am", 0, 34200])
def testApplicationTimeNotWrittenAsATimeRejected(validPackageDict, written):
  # No zone, no fraction, and never a number read as seconds since midnight.
  validPackageDict["applications"][0]["time"] = written
  assert any(f"a time of day is written HH:MM or HH:MM:SS, got {written!r}" in message
             for message in errorMessages(rejection(validPackageDict)))


def testApplicationTimeThatDoesNotExistRejected(validPackageDict):
  validPackageDict["applications"][0]["time"] = "24:30"
  errors = rejection(validPackageDict).value.errors()
  assert [error["loc"][-1] for error in errors] == ["time"]


def testApplicationDateThatDoesNotExistRejected(validPackageDict):
  validPackageDict["applications"][0]["date"] = "2025-02-30"
  errors = rejection(validPackageDict).value.errors()
  assert [error["loc"][-1] for error in errors] == ["date"]


@pytest.mark.parametrize("field, value, message", [
  ("pressure", {"value": 0, "unit": "kPa"}, "pressure must be greater than zero, got 0.0"),
  ("sprayVolume", {"value": -200, "unit": "L/ha"}, "sprayVolume must be greater than zero, got -200.0"),
  ("travelSpeed", {"value": 0, "unit": "km/h"}, "travelSpeed must be greater than zero, got 0.0"),
  ("windSpeed", {"value": -1, "unit": "m/s"}, "windSpeed must not be negative, got -1.0"),
])
def testImpossibleApplicationAmountRejected(validPackageDict, field, value, message):
  validPackageDict["applications"][0][field] = value
  assert any(message in text for text in errorMessages(rejection(validPackageDict)))


@pytest.mark.parametrize("field, value", [
  ("relativeHumidity", 100.5), ("relativeHumidity", -1), ("cloudCover", 101), ("cloudCover", float("nan")),
])
def testPercentageOutsideItsRangeRejected(validPackageDict, field, value):
  validPackageDict["applications"][0][field] = value
  errors = rejection(validPackageDict).value.errors()
  assert [error["loc"][-1] for error in errors] == [field]


def testUnknownSoilMoistureRejected(validPackageDict):
  validPackageDict["applications"][0]["soilMoisture"] = "damp"
  errors = rejection(validPackageDict).value.errors()
  assert [(error["type"], error["loc"][-1]) for error in errors] == [("enum", "soilMoisture")]


def testDuplicateTreatmentCodeRejected(validPackageDict):
  validPackageDict["treatments"][2]["treatmentCode"] = "T2"
  with pytest.raises(ValidationError) as excInfo:
    buildPackage(validPackageDict)
  assert any("duplicate treatmentCode values: ['T2']" in message
             for message in errorMessages(excInfo))


def testSingleTreatmentRejected(validPackageDict):
  validPackageDict["treatments"] = validPackageDict["treatments"][:1]
  with pytest.raises(ValidationError) as excInfo:
    buildPackage(validPackageDict)
  assert any(error["loc"][-1] == "treatments" for error in excInfo.value.errors())


# ---- assessment rules ---------------------------------------------------

def testNumericWithAllowedValuesRejected(validPackageDict):
  validPackageDict["ratings"][0]["allowedValues"] = ["a", "b"]
  with pytest.raises(ValidationError) as excInfo:
    buildPackage(validPackageDict)
  assert any("numeric type cannot define allowedValues" in message
             for message in errorMessages(excInfo))


def testNumericMinExceedsMaxRejected(validPackageDict):
  validPackageDict["ratings"][0]["minValue"] = 100.0
  validPackageDict["ratings"][0]["maxValue"] = 1.0
  with pytest.raises(ValidationError) as excInfo:
    buildPackage(validPackageDict)
  assert any("minValue 100.0 exceeds maxValue 1.0" in message
             for message in errorMessages(excInfo))


def testCategoricalWithoutAllowedValuesRejected(validPackageDict):
  del validPackageDict["ratings"][1]["allowedValues"]
  with pytest.raises(ValidationError) as excInfo:
    buildPackage(validPackageDict)
  assert any("must enumerate allowedValues" in message
             for message in errorMessages(excInfo))


def testOrdinalWithNumericRangeRejected(validPackageDict):
  validPackageDict["ratings"][1]["minValue"] = 0.0
  with pytest.raises(ValidationError) as excInfo:
    buildPackage(validPackageDict)
  assert any("cannot define a numeric range" in message
             for message in errorMessages(excInfo))


def testDuplicateAllowedValuesRejected(validPackageDict):
  validPackageDict["ratings"][1]["allowedValues"] = ["low", "low", "high"]
  with pytest.raises(ValidationError) as excInfo:
    buildPackage(validPackageDict)
  assert any("allowedValues contains duplicates" in message
             for message in errorMessages(excInfo))


def testDuplicateAssessmentCodeRejected(validPackageDict):
  validPackageDict["assessments"][1]["assessmentCode"] = "YIELD"
  with pytest.raises(ValidationError) as excInfo:
    buildPackage(validPackageDict)
  assert any("duplicate assessmentCode values: ['YIELD']" in message
             for message in errorMessages(excInfo))


def testEmptyAssessmentsRejected(validPackageDict):
  validPackageDict["assessments"] = []
  with pytest.raises(ValidationError) as excInfo:
    buildPackage(validPackageDict)
  assert any(error["loc"][-1] == "assessments" for error in excInfo.value.errors())


# ---- ratings and assessment occasions (decision 0017) -------------------

def testOneRatingTakenOnSeveralOccasions(validPackageDict):
  validPackageDict["applications"][0]["date"] = "2025-05-02"
  validPackageDict["assessments"] = [
    {"assessmentCode": "YIELD", "ratingCode": "YIELD"},
    {"assessmentCode": "SEV7", "ratingCode": "SEV", "date": "2025-05-09", "timedFromApplicationCode": "GS31"},
    {"assessmentCode": "SEV0", "ratingCode": "SEV", "date": "2025-05-01", "timedFromApplicationCode": "GS31"},
    {"assessmentCode": "SEVX", "ratingCode": "SEV", "timedFromApplicationCode": "GS39"},
  ]
  package = buildPackage(validPackageDict)
  assert package.ratingFor("SEV7") is package.ratingFor("SEV0") is package.ratings[1]
  assert package.daysAfterApplication("SEV7") == 7
  assert package.daysAfterApplication("SEV0") == -1
  # GS39 has no date yet, YIELD is timed from nothing: neither has a count of days.
  assert package.daysAfterApplication("SEVX") is None
  assert package.daysAfterApplication("YIELD") is None


def testAssessmentOfAnUndeclaredRatingRejected(validPackageDict):
  validPackageDict["assessments"][1]["ratingCode"] = "LODGE"
  assert any("assessment 'SEV': rating 'LODGE' is not declared in the package" in message
             for message in errorMessages(rejection(validPackageDict)))


def testAssessmentTimedFromAnUndeclaredApplicationRejected(validPackageDict):
  validPackageDict["assessments"][1]["timedFromApplicationCode"] = "GS99"
  assert any("assessment 'SEV': application 'GS99' is not declared in the package" in message
             for message in errorMessages(rejection(validPackageDict)))


def testDuplicateRatingCodeRejected(validPackageDict):
  validPackageDict["ratings"][1]["ratingCode"] = "YIELD"
  assert any("duplicate ratingCode values: ['YIELD']" in message
             for message in errorMessages(rejection(validPackageDict)))


def testNonPositiveSampleSizeRejected(validPackageDict):
  validPackageDict["assessments"][0]["sampleSize"] = {"value": 0, "unit": "plants"}
  assert any("sampleSize must be greater than zero, got 0.0" in message
             for message in errorMessages(rejection(validPackageDict)))


def testCategoryRatingWithAUnitRejected(validPackageDict):
  validPackageDict["ratings"][1]["unit"] = "%"
  assert any("rating 'SEV': ordinal type cannot declare a unit" in message
             for message in errorMessages(rejection(validPackageDict)))


def testAssessmentDateNotWrittenAsADateRejected(validPackageDict):
  validPackageDict["assessments"][0]["date"] = 20250502
  assert any("a date is written YYYY-MM-DD, got 20250502" in message
             for message in errorMessages(rejection(validPackageDict)))


# ---- targets (decision 0018) ----------------------------------------------

def withTarget(packageDict):
  packageDict["targets"] = [
    {"targetCode": "SEPT", "name": "Septoria leaf blotch", "kind": "disease",
     "scientificName": "Zymoseptoria tritici", "eppoCode": "SEPTTR"},
  ]
  packageDict["ratings"][1]["targetCode"] = "SEPT"
  return packageDict


def testRatingNamesTheTargetItRates(validPackageDict):
  package = buildPackage(withTarget(validPackageDict))
  assert package.ratings[1].targetCode == "SEPT"
  target = package.targets[0]
  assert (target.kind, target.scientificName, target.eppoCode) == (
    TargetKind.disease, "Zymoseptoria tritici", "SEPTTR",
  )


def testRatingOfAnUndeclaredTargetRejected(validPackageDict):
  withTarget(validPackageDict)["ratings"][1]["targetCode"] = "RUST"
  assert any("rating 'SEV': target 'RUST' is not declared in the package" in message
             for message in errorMessages(rejection(validPackageDict)))


def testDuplicateTargetCodeRejected(validPackageDict):
  withTarget(validPackageDict)["targets"].append(
    {"targetCode": "SEPT", "name": "Other", "kind": "other"},
  )
  assert any("duplicate targetCode values: ['SEPT']" in message
             for message in errorMessages(rejection(validPackageDict)))


@pytest.mark.parametrize("written", ["septtr", "SEPT", "SEPTTRX", "SEPT-T"])
def testEPPOCodeOfTheWrongShapeRejected(validPackageDict, written):
  withTarget(validPackageDict)["targets"][0]["eppoCode"] = written
  errors = rejection(validPackageDict).value.errors()
  assert [(error["type"], error["loc"][-1]) for error in errors] == [("string_pattern_mismatch", "eppoCode")]


def testGenusLevelEPPOCodeAccepted(validPackageDict):
  # Codes for a genus or a group start with a digit, e.g. 1SEPTG.
  withTarget(validPackageDict)["targets"][0]["eppoCode"] = "1SEPTG"
  assert buildPackage(validPackageDict).targets[0].eppoCode == "1SEPTG"


# ---- planting, soil and weather (decision 0019) ---------------------------

def testPlantingSoilAndWeatherAreRecorded(validPackageDict):
  validPackageDict["planting"] = {"cultivar": "Skyfall", "sowingDate": "2024-10-01",
                                  "emergenceDate": "2024-10-12", "seedingRate": {"value": 160, "unit": "kg/ha"}}
  validPackageDict["soil"] = {"pH": 6.8, "pHMethod": "CaCl2", "organicMatter": 2.4}
  validPackageDict["weather"] = [{"date": "2025-05-01", "rainfall": {"value": 0, "unit": "mm"}}]
  package = buildPackage(validPackageDict)
  assert package.planting.seedingRate == Quantity(value=160.0, unit="kg/ha")
  assert (package.soil.pH, package.soil.pHMethod) == (6.8, "CaCl2")
  assert package.weather[0].rainfall == Quantity(value=0.0, unit="mm")


def testEmergenceBeforeSowingRejected(validPackageDict):
  validPackageDict["planting"] = {"sowingDate": "2024-10-12", "emergenceDate": "2024-10-01"}
  assert any("emergenceDate 2024-10-01 is before sowingDate 2024-10-12" in message
             for message in errorMessages(rejection(validPackageDict)))


@pytest.mark.parametrize("block", ["planting", "soil"])
def testEmptyBlockRejected(validPackageDict, block):
  # Stored, an empty block and no block would look the same; so the empty one is refused.
  validPackageDict[block] = {}
  assert any(f"{block} holds nothing; leave it out instead" in message
             for message in errorMessages(rejection(validPackageDict)))


@pytest.mark.parametrize("field, value", [("pH", 14.5), ("pH", -0.1), ("organicMatter", 101)])
def testSoilValueOutsideItsRangeRejected(validPackageDict, field, value):
  validPackageDict["soil"] = {field: value}
  errors = rejection(validPackageDict).value.errors()
  assert [error["loc"][-1] for error in errors] == [field]


def testPHMethodWithoutAPHRejected(validPackageDict):
  validPackageDict["soil"] = {"pHMethod": "CaCl2"}
  assert any("pHMethod is given without a pH" in message
             for message in errorMessages(rejection(validPackageDict)))


def testCropEPPOCodeOfTheWrongShapeRejected(validPackageDict):
  validPackageDict["planting"] = {"cropEPPOCode": "wheat"}
  errors = rejection(validPackageDict).value.errors()
  assert [(error["type"], error["loc"][-1]) for error in errors] == [("string_pattern_mismatch", "cropEPPOCode")]


def testNegativeRainfallRejected(validPackageDict):
  validPackageDict["weather"] = [{"date": "2025-05-01", "rainfall": {"value": -1, "unit": "mm"}}]
  assert any("rainfall must not be negative, got -1.0" in message
             for message in errorMessages(rejection(validPackageDict)))


def testMinimumAboveMaximumRejected(validPackageDict):
  validPackageDict["weather"] = [{"date": "2025-05-01", "minimumTemperature": {"value": 20, "unit": "C"},
                                  "maximumTemperature": {"value": 12, "unit": "C"}}]
  assert any("weather record for 2025-05-01: minimum 20.0 is above maximum 12.0" in message
             for message in errorMessages(rejection(validPackageDict)))


def testTemperaturesInDifferentUnitsRejected(validPackageDict):
  validPackageDict["weather"] = [{"date": "2025-05-01", "minimumTemperature": {"value": 5, "unit": "C"},
                                  "maximumTemperature": {"value": 60, "unit": "F"}}]
  assert any("temperatures in 'C' and 'F' cannot be compared" in message
             for message in errorMessages(rejection(validPackageDict)))


def testEmptyWeatherRecordRejected(validPackageDict):
  validPackageDict["weather"] = [{"date": "2025-05-01"}]
  assert any("weather record for 2025-05-01 holds nothing" in message
             for message in errorMessages(rejection(validPackageDict)))


@pytest.mark.parametrize("dates", [["2025-05-02", "2025-05-01"], ["2025-05-01", "2025-05-01"]])
def testWeatherOutOfOrderOrRepeatedRejected(validPackageDict, dates):
  validPackageDict["weather"] = [{"date": day, "rainfall": {"value": 1, "unit": "mm"}} for day in dates]
  assert any(f"one per day in date order; {dates[1]} follows {dates[0]}" in message
             for message in errorMessages(rejection(validPackageDict)))


# ---- site and plots (decision 0024) --------------------------------------

@pytest.mark.parametrize("site, message", [
  ({"latitude": 91, "longitude": 0}, "less than or equal to 90"),
  ({"latitude": 10, "longitude": -181}, "greater than or equal to -180"),
  ({"latitude": 10}, "a position needs both latitude and longitude"),
  ({}, "siteDetails holds nothing; leave it out instead"),
])
def testSiteDetailsAreChecked(validPackageDict, site, message):
  validPackageDict["siteDetails"] = site
  assert any(message in text for text in errorMessages(rejection(validPackageDict)))


@pytest.mark.parametrize("dimensions, message", [
  ({"grossLength": {"value": 8, "unit": "m"}, "netLength": {"value": 9, "unit": "m"}},
   "netLength 9.0 m is larger than grossLength 8.0 m"),
  ({"alleyWidth": {"value": 0, "unit": "m"}}, "alleyWidth must be greater than zero, got 0.0"),
  ({}, "plotDimensions holds nothing; leave it out instead"),
])
def testPlotDimensionsAreChecked(validPackageDict, dimensions, message):
  validPackageDict["design"]["plotDimensions"] = dimensions
  assert any(message in text for text in errorMessages(rejection(validPackageDict)))


def testNetPlotInAnotherUnitIsNotCompared(validPackageDict):
  # 9 ft is shorter than 8 m; units are kept as written, not converted, so no comparison is made.
  validPackageDict["design"]["plotDimensions"] = {
    "grossLength": {"value": 8, "unit": "m"}, "netLength": {"value": 9, "unit": "ft"},
  }
  assert buildPackage(validPackageDict).design.plotDimensions.netLength.unit == "ft"


# ---- design rules -------------------------------------------------------

def testReplicationsBelowTwoRejected(validPackageDict):
  validPackageDict["design"]["replications"] = 1
  with pytest.raises(ValidationError) as excInfo:
    buildPackage(validPackageDict)
  assert any(error["loc"][-1] == "replications" for error in excInfo.value.errors())


def testNegativeSeedRejected(validPackageDict):
  validPackageDict["design"]["randomizationSeed"] = -1
  with pytest.raises(ValidationError) as excInfo:
    buildPackage(validPackageDict)
  assert any(error["loc"][-1] == "randomizationSeed" for error in excInfo.value.errors())


# ---- structural rules ---------------------------------------------------

def testUnknownFieldRejected(validPackageDict):
  validPackageDict["trial"]["unexpectedField"] = "x"
  with pytest.raises(ValidationError) as excInfo:
    buildPackage(validPackageDict)
  assert any(error["type"] == "extra_forbidden" for error in excInfo.value.errors())
