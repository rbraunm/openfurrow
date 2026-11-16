# SPDX-License-Identifier: Apache-2.0
"""Tests for the Observation atom."""

import pytest
from pydantic import ValidationError

from openfurrow.schema import Observation


def testNumericObservationKeepsFloat():
  observation = Observation(plotNumber=101, assessmentCode="YIELD", value=4823.5)
  assert observation.value == 4823.5
  assert isinstance(observation.value, float)


def testCategoricalObservationKeepsString():
  observation = Observation(plotNumber=101, assessmentCode="SEV", value="moderate")
  assert observation.value == "moderate"
  assert isinstance(observation.value, str)


def testNumericLookingCodeNotCoercedToNumber():
  # A categorical code of "3" must stay a string under strict mode, not become 3.0.
  observation = Observation(plotNumber=101, assessmentCode="GRADE", value="3")
  assert observation.value == "3"
  assert isinstance(observation.value, str)


def testMissingValueIsNone():
  observation = Observation(plotNumber=101, assessmentCode="YIELD", value=None)
  assert observation.value is None


def testZeroPlotNumberRejected():
  with pytest.raises(ValidationError) as excInfo:
    Observation(plotNumber=0, assessmentCode="YIELD", value=1.0)
  assert any(error["loc"][-1] == "plotNumber" for error in excInfo.value.errors())


def testEmptyAssessmentCodeRejected():
  with pytest.raises(ValidationError) as excInfo:
    Observation(plotNumber=101, assessmentCode="", value=1.0)
  assert any(error["loc"][-1] == "assessmentCode" for error in excInfo.value.errors())


def testExtraFieldRejected():
  with pytest.raises(ValidationError) as excInfo:
    Observation(plotNumber=101, assessmentCode="YIELD", value=1.0, block=1)
  assert any(error["type"] == "extra_forbidden" for error in excInfo.value.errors())
