# SPDX-License-Identifier: Apache-2.0
"""Tests for the Shapiro-Wilk normality diagnostic (decision 0006).

Shapiro-Wilk uses Royston's AS R94, the same algorithm as scipy.stats.shapiro,
so W and the p-value are cross-checked against scipy across a range of sample
sizes and distributions. The n = 3 case has an exact closed form, checked
independently of scipy, and the fail-loud edges are checked directly.
"""

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy import stats

from openfurrow.analysis.diagnostics import (
  Assumptions,
  DiagnosticOutcome,
  assessAssumptions,
  brownForsythe,
  recommendTransform,
  shapiroWilk,
  shapiroWilkMinimum,
  shapiroWilkResiduals,
  tukeyNonAdditivity,
)
from openfurrow.design import generateRcbdLayout
from openfurrow.schema import MeasurementKind, Transform, TrialPackage
from openfurrow.schema.observation import Observation


# ---- analytic (independent of scipy) -------------------------------------

def testThreeEquallySpacedPointsAreMaximallyNormal():
  # For n = 3 the weights are (-1, 0, 1)/sqrt(2); three equally spaced points
  # give W = 1 exactly, and the exact n=3 p-value is then 1.
  w, pValue = shapiroWilk([0.0, 1.0, 2.0])
  assert w == pytest.approx(1.0, abs=1e-12)
  assert pValue == pytest.approx(1.0, abs=1e-12)


def testClearlyNonNormalSampleIsRejected():
  # Nine tight values and one far outlier: strongly non-normal, tiny p.
  sample = [0.0, 0.1, 0.2, 0.15, 0.05, 0.12, 0.08, 0.18, 0.03, 1000.0]
  _, pValue = shapiroWilk(sample)
  assert pValue < 0.01


# ---- cross-check against scipy -------------------------------------------

def testShapiroWilkMatchesScipy():
  rng = np.random.default_rng(20260701)
  generators = {
    "normal": lambda n: rng.normal(50.0, 10.0, n),
    "uniform": lambda n: rng.uniform(0.0, 1.0, n),
    "exponential": lambda n: rng.exponential(1.0, n),
  }
  for n in (3, 4, 5, 6, 7, 10, 11, 12, 15, 20, 30, 50, 100):
    for generate in generators.values():
      sample = list(generate(n))
      w, pValue = shapiroWilk(sample)
      reference = stats.shapiro(sample)
      assert w == pytest.approx(reference.statistic, abs=1e-7)
      assert pValue == pytest.approx(reference.pvalue, abs=1e-6)


# ---- fail-loud edges -----------------------------------------------------

def testRejectsTooFewValues():
  with pytest.raises(ValueError, match="at least"):
    shapiroWilk([1.0, 2.0])
  assert shapiroWilkMinimum == 3


def testRejectsConstantSample():
  with pytest.raises(ValueError, match="constant"):
    shapiroWilk([5.0, 5.0, 5.0, 5.0])


# ---- Brown-Forsythe vs scipy.levene(center='median') ---------------------

def testBrownForsytheMatchesScipyLevene():
  rng = np.random.default_rng(101)
  for blockCount, treatmentCount in [(6, 3), (15, 4), (5, 5), (10, 3), (8, 4)]:
    matrix = rng.normal(50.0, 10.0, (blockCount, treatmentCount)) + rng.normal(0.0, 3.0, (1, treatmentCount))
    outcome = brownForsythe(matrix)
    columns = [list(matrix[:, j]) for j in range(treatmentCount)]
    reference = stats.levene(*columns, center="median")
    assert outcome.computed is True
    assert outcome.statistic == pytest.approx(reference.statistic, abs=1e-9)
    assert outcome.pValue == pytest.approx(reference.pvalue, abs=1e-9)


def testBrownForsytheNotComputedWhenTooSmall():
  outcome = brownForsythe(np.array([[1.0, 2.0, 3.0]]))  # a single block
  assert outcome.computed is False
  assert "at least two" in outcome.interpretation


# ---- Tukey non-additivity vs statsmodels fitted-square model -------------

def _tukeyReference(matrix):
  blockCount, treatmentCount = matrix.shape
  rows = [
    {"y": float(matrix[i, j]), "block": f"B{i}", "treatment": f"T{j}"}
    for i in range(blockCount) for j in range(treatmentCount)
  ]
  frame = pd.DataFrame(rows)
  additive = smf.ols("y ~ C(treatment) + C(block)", data=frame).fit()
  frame["fittedSquared"] = np.asarray(additive.fittedvalues) ** 2
  augmented = smf.ols("y ~ C(treatment) + C(block) + fittedSquared", data=frame).fit()
  table = sm.stats.anova_lm(augmented, typ=1)
  return float(table.loc["fittedSquared", "F"]), float(table.loc["fittedSquared", "PR(>F)"])


def testTukeyMatchesStatsmodels():
  rng = np.random.default_rng(202)
  additive = 50.0 + np.add.outer(rng.normal(0, 5, 6), rng.normal(0, 5, 4)) + rng.normal(0, 1, (6, 4))
  rowEffect = rng.normal(0, 5, 7)
  columnEffect = rng.normal(0, 5, 5)
  interaction = (50.0 + np.add.outer(rowEffect, columnEffect)
                 + 0.05 * np.outer(rowEffect, columnEffect) + rng.normal(0, 0.5, (7, 5)))
  for matrix in (additive, interaction):
    outcome = tukeyNonAdditivity(matrix)
    referenceF, referenceP = _tukeyReference(matrix)
    assert outcome.computed is True
    assert outcome.numeratorDegreesOfFreedom == 1
    assert outcome.statistic == pytest.approx(referenceF, rel=1e-9, abs=1e-9)
    assert outcome.pValue == pytest.approx(referenceP, rel=1e-9, abs=1e-9)


def testTukeyDetectsInjectedInteraction():
  rng = np.random.default_rng(7)
  rowEffect = rng.normal(0, 5, 8)
  columnEffect = rng.normal(0, 5, 5)
  matrix = (50.0 + np.add.outer(rowEffect, columnEffect)
            + 0.08 * np.outer(rowEffect, columnEffect) + rng.normal(0, 0.3, (8, 5)))
  assert tukeyNonAdditivity(matrix).pValue < 0.01


def testTukeyNotComputedWhenTooFewErrorDf():
  outcome = tukeyNonAdditivity(np.array([[1.0, 2.0], [3.0, 5.0]]))  # 2 x 2 leaves no remainder df
  assert outcome.computed is False
  assert "too few error degrees of freedom" in outcome.interpretation


# ---- Shapiro-Wilk on residuals -------------------------------------------

def testShapiroWilkResidualsMatchesScipyOnResiduals():
  rng = np.random.default_rng(303)
  matrix = 50.0 + np.add.outer(rng.normal(0, 5, 10), rng.normal(0, 4, 4)) + rng.normal(0, 2, (10, 4))
  grand = float(matrix.mean())
  fitted = matrix.mean(axis=0)[None, :] + matrix.mean(axis=1)[:, None] - grand
  residuals = (matrix - fitted).flatten()
  outcome = shapiroWilkResiduals(matrix)
  reference = stats.shapiro(residuals.tolist())
  assert outcome.statisticName == "W"
  assert outcome.statistic == pytest.approx(reference.statistic, abs=1e-7)
  assert outcome.pValue == pytest.approx(reference.pvalue, abs=1e-6)


# ---- assessAssumptions integration on real stirret.borers data -----------

def _stirretSetup(assessmentColumn):
  import csv
  from pathlib import Path
  cells = {}
  path = Path(__file__).parent / "fixtures" / "stirretBorers.csv"
  with path.open() as handle:
    for row in csv.DictReader(handle):
      cells[(row["trt"], int(row["block"]))] = float(row[assessmentColumn])
  package = TrialPackage.model_validate({
    "schemaVersion": "0.1.0",
    "trial": {"trialCode": "STIRRET-1935", "title": "Corn borer", "crop": "Maize",
              "season": "1935", "site": "Ottawa", "objective": "control"},
    "treatments": [{"treatmentCode": t, "name": t} for t in ("None", "Early", "Late", "Both")],
    "design": {"designType": "rcbd", "replications": 15, "randomizationSeed": 1},
    "assessments": [{"assessmentCode": "y", "name": "count", "dataType": "numeric", "minValue": 0}],
  })
  layout = generateRcbdLayout(package)
  observations = [
    Observation(plotNumber=plot.plotNumber, assessmentCode="y", value=cells[(plot.treatmentCode, plot.block)])
    for plot in layout.plots
  ]
  return package, layout, observations


def testAssessAssumptionsReturnsThreeComputedChecks():
  package, layout, observations = _stirretSetup("count1")
  assumptions = assessAssumptions("y", package, layout, observations, significanceLevel=0.05)
  assert isinstance(assumptions, Assumptions)
  assert assumptions.equalVariance.computed
  assert assumptions.nonAdditivity.computed
  assert assumptions.normality.computed
  assert assumptions.equalVariance.statisticName == "F"
  assert assumptions.normality.statisticName == "W"


def testAssessAssumptionsFlagsCount2Violations():
  # count2 has unequal error variance and significant non-additivity (both p < 0.05).
  package, layout, observations = _stirretSetup("count2")
  assumptions = assessAssumptions("y", package, layout, observations, significanceLevel=0.05)
  assert assumptions.equalVariance.pValue < 0.05
  assert assumptions.nonAdditivity.pValue < 0.05


def testAssessAssumptionsRejectsBadSignificance():
  package, layout, observations = _stirretSetup("count1")
  with pytest.raises(ValueError, match="significanceLevel must be in"):
    assessAssumptions("y", package, layout, observations, significanceLevel=1.5)


# ---- transform recommendation (advisory, never applied) --------------------

def _flaggedOutcome(pValue):
  return DiagnosticOutcome(
    name="check", computed=True, statisticName="F", statistic=5.0,
    numeratorDegreesOfFreedom=3, denominatorDegreesOfFreedom=40,
    pValue=pValue, interpretation="x")


def testRecommendNamesCanonicalTransformForKnownKind():
  flagged, clean = _flaggedOutcome(0.01), _flaggedOutcome(0.5)
  countMessage = recommendTransform((flagged, clean, clean), MeasurementKind.count, Transform.none, 0.05)
  proportionMessage = recommendTransform((clean, clean, flagged), MeasurementKind.proportion, Transform.none, 0.05)
  continuousMessage = recommendTransform((clean, flagged, clean), MeasurementKind.continuous, Transform.none, 0.05)
  assert "sqrt" in countMessage and "count" in countMessage
  assert "arcsinSqrt" in proportionMessage
  assert "log" in continuousMessage


def testRecommendIsGenericWhenKindUnspecified():
  flagged, clean = _flaggedOutcome(0.01), _flaggedOutcome(0.5)
  message = recommendTransform((flagged, clean, clean), MeasurementKind.unspecified, Transform.none, 0.05)
  assert message is not None
  assert "measurementKind" in message


def testNoRecommendationWhenAssumptionsHold():
  clean = _flaggedOutcome(0.5)
  assert recommendTransform((clean, clean, clean), MeasurementKind.count, Transform.none, 0.05) is None


def testNoRecommendationWhenAlreadyTransformed():
  flagged = _flaggedOutcome(0.001)
  assert recommendTransform((flagged, flagged, flagged), MeasurementKind.count, Transform.sqrt, 0.05) is None
