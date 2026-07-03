# SPDX-License-Identifier: Apache-2.0
"""Tests for the variance-stabilizing transforms and their schema fields (decision 0006).

Checkpoint A is math and schema only: the forward and back transforms with their
fail-loud domains, the declared-transform-versus-kind sanity check, the new
assessment fields, and proof that declaring a transform moves the content hash.
Nothing here exercises the analysis path; that is checkpoint B.
"""

import math

import pytest

from openfurrow.analysis.transforms import (
  TransformError,
  applyTransform,
  backTransformMean,
  checkTransformKind,
  compatibleTransforms,
)
from openfurrow.schema import (
  MeasurementKind,
  Transform,
  TrialDocument,
  TrialPackage,
  contentHash,
)


# ---- forward transforms: known values --------------------------------------

def testNoneIsIdentity():
  assert applyTransform(Transform.none, [0.0, 1.5, 42.0]) == [0.0, 1.5, 42.0]


def testForwardKnownValues():
  assert applyTransform(Transform.sqrt, [0.0, 1.0, 4.0, 9.0]) == [0.0, 1.0, 2.0, 3.0]
  assert applyTransform(Transform.log, [1.0, math.e]) == pytest.approx([0.0, 1.0])
  assert applyTransform(Transform.arcsinSqrt, [0.0, 1.0]) == pytest.approx([0.0, math.pi / 2])
  assert applyTransform(Transform.logit, [0.5]) == pytest.approx([0.0])


# ---- back-transform and round-trip -----------------------------------------

def testBackTransformKnownValues():
  assert backTransformMean(Transform.none, 3.3) == 3.3
  assert backTransformMean(Transform.sqrt, 3.0) == pytest.approx(9.0)
  assert backTransformMean(Transform.log, 0.0) == pytest.approx(1.0)
  assert backTransformMean(Transform.arcsinSqrt, math.pi / 2) == pytest.approx(1.0)
  assert backTransformMean(Transform.logit, 0.0) == pytest.approx(0.5)


def testRoundTripInvertsForEachTransform():
  samples = {
    Transform.sqrt: [0.0, 2.5, 4.0, 100.0],
    Transform.log: [0.5, 1.0, math.e, 10.0],
    Transform.arcsinSqrt: [0.0, 0.25, 0.5, 0.75, 1.0],
    Transform.logit: [0.01, 0.3, 0.5, 0.9, 0.99],
  }
  for transform, values in samples.items():
    for value in values:
      forward = applyTransform(transform, [value])[0]
      assert backTransformMean(transform, forward) == pytest.approx(value, abs=1e-12)


# ---- fail-loud domains, naming the offending values ------------------------

def testSqrtRejectsNegative():
  with pytest.raises(TransformError, match="values >= 0") as excinfo:
    applyTransform(Transform.sqrt, [1.0, -4.0, 9.0])
  assert "-4" in str(excinfo.value)


def testLogRejectsNonPositive():
  with pytest.raises(TransformError, match="values > 0"):
    applyTransform(Transform.log, [1.0, 0.0])
  with pytest.raises(TransformError, match="values > 0"):
    applyTransform(Transform.log, [-2.0])


def testArcsinSqrtRejectsOutsideUnitInterval():
  with pytest.raises(TransformError, match="proportions in"):
    applyTransform(Transform.arcsinSqrt, [0.5, 1.5])
  with pytest.raises(TransformError, match="proportions in"):
    applyTransform(Transform.arcsinSqrt, [-0.1])


def testLogitRejectsBoundariesAndOutside():
  for bad in ([0.0], [1.0], [1.5], [-0.2]):
    with pytest.raises(TransformError, match="open interval"):
      applyTransform(Transform.logit, bad)


# ---- transform-versus-kind sanity check ------------------------------------

def testNoneAndUnspecifiedNeverRejected():
  for kind in MeasurementKind:
    checkTransformKind(Transform.none, kind)  # none is always allowed
  for transform in Transform:
    checkTransformKind(transform, MeasurementKind.unspecified)  # unspecified imposes nothing


def testCompatiblePairsPass():
  checkTransformKind(Transform.sqrt, MeasurementKind.count)
  checkTransformKind(Transform.log, MeasurementKind.count)
  checkTransformKind(Transform.arcsinSqrt, MeasurementKind.proportion)
  checkTransformKind(Transform.logit, MeasurementKind.proportion)
  checkTransformKind(Transform.sqrt, MeasurementKind.continuous)
  checkTransformKind(Transform.log, MeasurementKind.continuous)


def testIncompatiblePairsRejected():
  with pytest.raises(TransformError, match="not appropriate") as excinfo:
    checkTransformKind(Transform.logit, MeasurementKind.count)
  message = str(excinfo.value)
  assert "count" in message and "log, sqrt" in message
  for transform, kind in [
    (Transform.arcsinSqrt, MeasurementKind.count),
    (Transform.sqrt, MeasurementKind.proportion),
    (Transform.log, MeasurementKind.proportion),
    (Transform.logit, MeasurementKind.continuous),
    (Transform.arcsinSqrt, MeasurementKind.continuous),
  ]:
    with pytest.raises(TransformError, match="not appropriate"):
      checkTransformKind(transform, kind)


def testCompatibilityMapExcludesNone():
  for allowed in compatibleTransforms.values():
    assert Transform.none not in allowed


# ---- schema fields ---------------------------------------------------------

def _packageDict(assessment):
  return {
    "schemaVersion": "0.1.0",
    "trial": {"trialCode": "T1", "title": "t", "crop": "Maize", "season": "2025",
              "site": "s", "objective": "o"},
    "treatments": [{"treatmentCode": "A", "name": "A"}, {"treatmentCode": "B", "name": "B"}],
    "design": {"designType": "rcbd", "replications": 3, "randomizationSeed": 1},
    "assessments": [assessment],
  }


def testNumericAssessmentAcceptsTransformAndKind():
  package = TrialPackage.model_validate(_packageDict(
    {"assessmentCode": "Y", "name": "yield", "dataType": "numeric",
     "measurementKind": "count", "transform": "sqrt"}))
  assessment = package.assessments[0]
  assert assessment.transform is Transform.sqrt
  assert assessment.measurementKind is MeasurementKind.count


def testNumericAssessmentDefaultsAreNoneAndUnspecified():
  package = TrialPackage.model_validate(_packageDict(
    {"assessmentCode": "Y", "name": "yield", "dataType": "numeric"}))
  assessment = package.assessments[0]
  assert assessment.transform is Transform.none
  assert assessment.measurementKind is MeasurementKind.unspecified


def testSchemaAllowsAnyTransformOnNumericKindCheckIsSeparate():
  # The schema does not enforce transform/kind compatibility; that is the analysis
  # path's checkTransformKind. A numeric assessment may declare any of them.
  package = TrialPackage.model_validate(_packageDict(
    {"assessmentCode": "Y", "name": "yield", "dataType": "numeric",
     "measurementKind": "count", "transform": "logit"}))
  assert package.assessments[0].transform is Transform.logit


def testNonNumericCannotDeclareTransform():
  with pytest.raises(ValueError, match="cannot declare a transform"):
    TrialPackage.model_validate(_packageDict(
      {"assessmentCode": "C", "name": "color", "dataType": "categorical",
       "allowedValues": ["r", "g"], "transform": "sqrt"}))


def testNonNumericCannotDeclareMeasurementKind():
  with pytest.raises(ValueError, match="cannot declare a measurementKind"):
    TrialPackage.model_validate(_packageDict(
      {"assessmentCode": "C", "name": "color", "dataType": "categorical",
       "allowedValues": ["r", "g"], "measurementKind": "count"}))


# ---- the transform enters the content hash (decision 0006) -----------------

def _hashWith(**assessmentOverrides):
  assessment = {"assessmentCode": "Y", "name": "yield", "dataType": "numeric"}
  assessment.update(assessmentOverrides)
  package = TrialPackage.model_validate(_packageDict(assessment))
  return contentHash(TrialDocument(package=package))


def testDeclaringTransformMovesContentHash():
  assert _hashWith() != _hashWith(transform="sqrt")
  assert _hashWith(transform="sqrt") != _hashWith(transform="log")


def testMeasurementKindAlsoMovesContentHash():
  assert _hashWith() != _hashWith(measurementKind="count")
