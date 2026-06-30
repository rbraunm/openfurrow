# SPDX-License-Identifier: Apache-2.0
"""Tests for the trial package schema.

Each test exercises the real models. The valid-construction tests assert
concrete field values and the derived plot count; the rejection tests assert
that a specific malformed package raises and, where the rule is enforced by a
custom validator, that the failure names the offending entity.
"""

import pytest
from pydantic import ValidationError

from openfurrow.schema import AssessmentDataType, DesignType, TrialPackage


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
  assert package.assessments[1].dataType is AssessmentDataType.ordinal


def testPlotCountIsTreatmentsTimesReplications(validPackageDict):
  # 3 treatments x 4 replications.
  assert buildPackage(validPackageDict).plotCount == 12


def testPlotCountTracksDesignChange(validPackageDict):
  validPackageDict["design"]["replications"] = 6
  # Still 3 treatments, now 6 replications -> 18; proves the value is derived.
  assert buildPackage(validPackageDict).plotCount == 18


def testUntreatedControlNeedsNoProductOrRate(validPackageDict):
  # The control treatment (T1) carries no product, rate, or unit and is valid.
  package = buildPackage(validPackageDict)
  control = package.treatments[0]
  assert control.product is None
  assert control.rate is None
  assert control.rateUnit is None


def testNumericRangeWithMinBelowMaxAccepted(validPackageDict):
  validPackageDict["assessments"][0]["minValue"] = 0.0
  validPackageDict["assessments"][0]["maxValue"] = 20000.0
  package = buildPackage(validPackageDict)
  assert package.assessments[0].maxValue == 20000.0


# ---- treatment rules ----------------------------------------------------

def testRateWithoutUnitRejected(validPackageDict):
  del validPackageDict["treatments"][1]["rateUnit"]
  with pytest.raises(ValidationError) as excInfo:
    buildPackage(validPackageDict)
  assert any("rate and rateUnit must be provided together" in message
             for message in errorMessages(excInfo))


def testUnitWithoutRateRejected(validPackageDict):
  del validPackageDict["treatments"][1]["rate"]
  with pytest.raises(ValidationError) as excInfo:
    buildPackage(validPackageDict)
  assert any("rate and rateUnit must be provided together" in message
             for message in errorMessages(excInfo))


def testNonPositiveRateRejected(validPackageDict):
  validPackageDict["treatments"][1]["rate"] = 0.0
  with pytest.raises(ValidationError) as excInfo:
    buildPackage(validPackageDict)
  assert any(error["loc"][-1] == "rate" for error in excInfo.value.errors())


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
  validPackageDict["assessments"][0]["allowedValues"] = ["a", "b"]
  with pytest.raises(ValidationError) as excInfo:
    buildPackage(validPackageDict)
  assert any("numeric type cannot define allowedValues" in message
             for message in errorMessages(excInfo))


def testNumericMinExceedsMaxRejected(validPackageDict):
  validPackageDict["assessments"][0]["minValue"] = 100.0
  validPackageDict["assessments"][0]["maxValue"] = 1.0
  with pytest.raises(ValidationError) as excInfo:
    buildPackage(validPackageDict)
  assert any("minValue 100.0 exceeds maxValue 1.0" in message
             for message in errorMessages(excInfo))


def testCategoricalWithoutAllowedValuesRejected(validPackageDict):
  del validPackageDict["assessments"][1]["allowedValues"]
  with pytest.raises(ValidationError) as excInfo:
    buildPackage(validPackageDict)
  assert any("must enumerate allowedValues" in message
             for message in errorMessages(excInfo))


def testOrdinalWithNumericRangeRejected(validPackageDict):
  validPackageDict["assessments"][1]["minValue"] = 0.0
  with pytest.raises(ValidationError) as excInfo:
    buildPackage(validPackageDict)
  assert any("cannot define a numeric range" in message
             for message in errorMessages(excInfo))


def testDuplicateAllowedValuesRejected(validPackageDict):
  validPackageDict["assessments"][1]["allowedValues"] = ["low", "low", "high"]
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
